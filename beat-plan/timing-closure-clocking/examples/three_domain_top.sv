// three_domain_top.sv -- how the pack wires a three-clock design. Integration example,
// not Forge engine RTL: the "core" here is a placeholder accumulator.
// Forge Feature 5 (timing-closure / clocking pack).
//
// Domains (FPGA plan in docs/CLOCKING_SPEC.md):
//   clk_host  host / shell interface clock (rate set by the platform)
//   clk_core  compute clock, the 250 MHz FPGA target
//   clk_mem   memory-controller user clock (rate set by the platform)
// Crossings, one primitive each:
//   host -> core  command stream          cdc_async_fifo (LUTRAM, Gray pointers)
//   core -> host  result stream           cdc_async_fifo
//   host -> core  CSR word                cdc_handshake
//   mem  -> core  refill stream           cdc_async_fifo
//   mem  -> core  refill-done event       cdc_pulse_sync
//   core -> host  busy status (level)     cdc_sync_bit
//   one raw reset -> cdc_reset_sync in every domain
// Inside clk_core, the two halves of the core talk through slr_crossing, as they would
// if the floorplan put them in different SLRs.
module three_domain_top #(
  parameter int unsigned W = 32
) (
  input  logic         clk_host,
  input  logic         clk_core,
  input  logic         clk_mem,
  input  logic         arst_n,
  // host side
  input  logic         host_cmd_valid,
  input  logic [W-1:0] host_cmd_data,
  output logic         host_cmd_full,
  output logic         host_res_valid,
  input  logic         host_res_ready,
  output logic [W-1:0] host_res_data,
  input  logic         host_csr_valid,
  output logic         host_csr_ready,
  input  logic [31:0]  host_csr_data,
  output logic         host_core_busy,
  // memory side
  input  logic         mem_valid,
  input  logic [W-1:0] mem_data,
  output logic         mem_full,
  input  logic         mem_done,
  output logic         mem_done_busy
);

  // ------------------------------------------------------------------ resets
  logic rst_host_n, rst_core_n, rst_mem_n;
  cdc_reset_sync #(.STAGES(2)) u_rst_host (.clk(clk_host), .arst_n(arst_n), .rst_n(rst_host_n));
  cdc_reset_sync #(.STAGES(2)) u_rst_core (.clk(clk_core), .arst_n(arst_n), .rst_n(rst_core_n));
  cdc_reset_sync #(.STAGES(2)) u_rst_mem  (.clk(clk_mem),  .arst_n(arst_n), .rst_n(rst_mem_n));

  // --------------------------------------- input registers in their own domains
  logic         cmd_v_q, csr_v_q, mem_v_q, mem_done_q;
  logic [W-1:0] cmd_d_q, mem_d_q;
  logic [31:0]  csr_d_q;
  always_ff @(posedge clk_host or negedge rst_host_n) begin
    if (!rst_host_n) begin cmd_v_q <= 1'b0; csr_v_q <= 1'b0; end
    else begin cmd_v_q <= host_cmd_valid; csr_v_q <= host_csr_valid; end
  end
  always_ff @(posedge clk_host) begin cmd_d_q <= host_cmd_data; csr_d_q <= host_csr_data; end
  always_ff @(posedge clk_mem or negedge rst_mem_n) begin
    if (!rst_mem_n) begin mem_v_q <= 1'b0; mem_done_q <= 1'b0; end
    else begin mem_v_q <= mem_valid; mem_done_q <= mem_done; end
  end
  always_ff @(posedge clk_mem) mem_d_q <= mem_data;

  // ---------------------------------------------------------- host -> core cmd
  logic         cmd_empty, cmd_pop;
  logic [W-1:0] cmd_rdata;
  /* verilator lint_off UNUSEDSIGNAL */   // level outputs unused in this example
  logic [$clog2(16):0] cmd_wfree, cmd_rlevel;
  /* verilator lint_on UNUSEDSIGNAL */
  cdc_async_fifo #(.WIDTH(W), .DEPTH(16), .STAGES(2)) u_cmd_fifo (
    .wclk(clk_host), .wrst_n(rst_host_n), .winc(cmd_v_q), .wdata(cmd_d_q), .wfull(host_cmd_full), .wfree(cmd_wfree),
    .rclk(clk_core), .rrst_n(rst_core_n), .rinc(cmd_pop), .rdata(cmd_rdata), .rempty(cmd_empty), .rlevel(cmd_rlevel));

  // ---------------------------------------------------------- mem -> core refill
  logic         ref_empty, ref_pop;
  logic [W-1:0] ref_rdata;
  /* verilator lint_off UNUSEDSIGNAL */
  logic [$clog2(16):0] ref_wfree, ref_rlevel;
  /* verilator lint_on UNUSEDSIGNAL */
  cdc_async_fifo #(.WIDTH(W), .DEPTH(16), .STAGES(2)) u_ref_fifo (
    .wclk(clk_mem), .wrst_n(rst_mem_n), .winc(mem_v_q), .wdata(mem_d_q), .wfull(mem_full), .wfree(ref_wfree),
    .rclk(clk_core), .rrst_n(rst_core_n), .rinc(ref_pop), .rdata(ref_rdata), .rempty(ref_empty), .rlevel(ref_rlevel));

  logic ref_done_core;
  /* verilator lint_off PINCONNECTEMPTY */   // src_accept not needed: mem_done_busy is exported
  cdc_pulse_sync #(.STAGES(2)) u_done (
    .clk_src(clk_mem), .rst_src_n(rst_mem_n), .src_pulse(mem_done_q), .src_busy(mem_done_busy), .src_accept(),
    .clk_dst(clk_core), .rst_dst_n(rst_core_n), .dst_pulse(ref_done_core));
  /* verilator lint_on PINCONNECTEMPTY */

  // ------------------------------------------------------------ host -> core CSR
  logic        csr_core_valid;
  logic [31:0] csr_core_data;
  cdc_handshake #(.WIDTH(32), .STAGES(2)) u_csr (
    .clk_src(clk_host), .rst_src_n(rst_host_n), .src_valid(csr_v_q), .src_ready(host_csr_ready), .src_data(csr_d_q),
    .clk_dst(clk_core), .rst_dst_n(rst_core_n), .dst_valid(csr_core_valid), .dst_ready(1'b1), .dst_data(csr_core_data));

  // ---------------------------------------------------------------- core (clk_core)
  // Half A takes commands (and refill words) and sends them across the SLR boundary
  // to half B, which accumulates and produces results.
  logic         a_valid, a_ready;
  logic [W-1:0] a_data, scale_q;
  logic         ref_seen_q;
  assign cmd_pop = !cmd_empty && a_ready;
  assign ref_pop = !ref_empty && cmd_empty && a_ready;        // commands first
  assign a_valid = !cmd_empty || !ref_empty;
  assign a_data  = !cmd_empty ? (cmd_rdata ^ scale_q) : ref_rdata;

  always_ff @(posedge clk_core or negedge rst_core_n) begin
    if (!rst_core_n) begin scale_q <= '0; ref_seen_q <= 1'b0; end
    else begin
      if (csr_core_valid) scale_q <= csr_core_data[W-1:0];
      if (ref_done_core)  ref_seen_q <= 1'b1;
    end
  end

  logic         b_valid, b_ready;
  logic [W-1:0] b_data;
  slr_crossing #(.WIDTH(W), .FWD_STAGES(2), .BWD_STAGES(2), .FIFO_DEPTH(8)) u_slr (
    .clk(clk_core), .rst_n(rst_core_n),
    .s_valid(a_valid), .s_ready(a_ready), .s_data(a_data),
    .m_valid(b_valid), .m_ready(b_ready), .m_data(b_data));

  logic [W-1:0] acc_q;
  logic         res_push;
  logic         res_full;
  assign b_ready  = !res_full;
  assign res_push = b_valid && b_ready;
  always_ff @(posedge clk_core or negedge rst_core_n) begin
    if (!rst_core_n) acc_q <= '0;
    else if (res_push) acc_q <= acc_q + b_data;
  end

  // ------------------------------------------------------------ core -> host results
  logic         res_empty;
  /* verilator lint_off UNUSEDSIGNAL */
  logic [$clog2(8):0] res_wfree, res_rlevel;
  /* verilator lint_on UNUSEDSIGNAL */
  cdc_async_fifo #(.WIDTH(W), .DEPTH(8), .STAGES(2)) u_res_fifo (
    .wclk(clk_core), .wrst_n(rst_core_n), .winc(res_push), .wdata(acc_q + b_data), .wfull(res_full), .wfree(res_wfree),
    .rclk(clk_host), .rrst_n(rst_host_n), .rinc(host_res_ready), .rdata(host_res_data), .rempty(res_empty), .rlevel(res_rlevel));
  assign host_res_valid = !res_empty;

  // ------------------------------------------------------------ core -> host busy
  logic busy_core_q;
  always_ff @(posedge clk_core or negedge rst_core_n) begin
    if (!rst_core_n) busy_core_q <= 1'b0;
    else             busy_core_q <= !cmd_empty || !ref_empty || b_valid || ref_seen_q;
  end
  cdc_sync_bit #(.WIDTH(1), .STAGES(2)) u_busy (
    .clk_dst(clk_host), .rst_dst_n(rst_host_n), .d_async(busy_core_q), .q(host_core_busy));

endmodule
