// cdc_handshake.sv -- multi-bit word crossing with a 2-phase request/acknowledge.
// Forge Feature 5 pack RTL (not Forge engine RTL).
//
// For low-rate words: CSR writes, configuration, status snapshots, a token count.
// One word per round trip (roughly 2*STAGES+3 cycles of the slower clock). For streams,
// use cdc_async_fifo.
//
// Why the data bits are safe without their own synchronizers: hold_q is loaded once,
// then stays stable until the acknowledge comes back. The destination copies it only
// after the request toggle has passed STAGES synchronizer flops, so hold_q has been
// stable for at least one destination period. The timing constraint that makes this
// true on silicon/FPGA is in constraints/: set_max_delay -datapath_only from hold_q to
// dst_q, no larger than one destination period.
module cdc_handshake #(
  parameter int unsigned WIDTH  = 32,
  parameter int unsigned STAGES = 2
) (
  input  logic             clk_src,
  input  logic             rst_src_n,
  input  logic             src_valid,
  output logic             src_ready,
  input  logic [WIDTH-1:0] src_data,

  input  logic             clk_dst,
  input  logic             rst_dst_n,
  output logic             dst_valid,
  input  logic             dst_ready,
  output logic [WIDTH-1:0] dst_data
);

  // ------------------------------ source domain ------------------------------
  logic             req_tgl;     // flips once per accepted word
  logic             ack_tgl_s;   // destination acknowledge, synchronized
  (* cdc_hold = "true" *)
  logic [WIDTH-1:0] hold_q;      // stable while a word is in flight

`ifdef CDC_MUTANT_NO_ACK_WAIT
  // Test-only mutation (formal/ negative test): source does not wait for the acknowledge.
  assign src_ready = 1'b1;
`else
  assign src_ready = (req_tgl == ack_tgl_s);
`endif

  always_ff @(posedge clk_src or negedge rst_src_n) begin
    if (!rst_src_n)                  req_tgl <= 1'b0;
    else if (src_valid && src_ready) req_tgl <= ~req_tgl;
  end

  always_ff @(posedge clk_src) begin
    if (src_valid && src_ready) hold_q <= src_data;
  end

  // --------------------------- destination domain ----------------------------
  logic             req_tgl_d;   // req_tgl synchronized into clk_dst
  logic             ack_tgl;     // flips when the destination has copied the word
  logic             dvalid_q;
  logic [WIDTH-1:0] dst_q;
  logic             pending;
  logic             take;

  cdc_sync_bit #(.WIDTH(1), .STAGES(STAGES)) u_req_sync (
    .clk_dst(clk_dst), .rst_dst_n(rst_dst_n), .d_async(req_tgl), .q(req_tgl_d));

  assign pending = (req_tgl_d != ack_tgl);
  assign take    = pending && (!dvalid_q || dst_ready);

  always_ff @(posedge clk_dst or negedge rst_dst_n) begin
    if (!rst_dst_n) begin
      ack_tgl  <= 1'b0;
      dvalid_q <= 1'b0;
    end else if (take) begin
      ack_tgl  <= ~ack_tgl;
      dvalid_q <= 1'b1;
    end else if (dst_ready) begin
      dvalid_q <= 1'b0;
    end
  end

  // Qualified capture: the enable (take) comes from the synchronized request.
  always_ff @(posedge clk_dst) begin
    if (take) dst_q <= hold_q;
  end

  assign dst_valid = dvalid_q;
  assign dst_data  = dst_q;

  cdc_sync_bit #(.WIDTH(1), .STAGES(STAGES)) u_ack_sync (
    .clk_dst(clk_src), .rst_dst_n(rst_src_n), .d_async(ack_tgl), .q(ack_tgl_s));

`ifdef FORMAL
  // ---- environment ----
  reg [1:0] f_gstep = 2'd0;
  always @($global_clock) if (f_gstep != 2'd3) f_gstep <= f_gstep + 2'd1;
  always @(*) if (f_gstep < 2'd2) begin assume(!rst_src_n); assume(!rst_dst_n); end
  always @($global_clock) if (f_gstep != 2'd0) begin
    if ($past(rst_src_n)) assume(rst_src_n);
    if ($past(rst_dst_n)) assume(rst_dst_n);
  end

  // ---- word accounting with an arbitrary tracked word ----
  // Words are numbered in acceptance order. For an arbitrary index f_idx the
  // environment supplies the arbitrary value f_val; the destination must deliver
  // exactly that value as word number f_idx: nothing lost, duplicated, reordered or
  // corrupted, for any clock interleaving.
  reg [3:0] f_sent = 4'd0, f_rcvd = 4'd0;
  (* anyconst *) logic [3:0]       f_idx;
  (* anyconst *) logic [WIDTH-1:0] f_val;

  always @(posedge clk_src) if (rst_src_n && src_valid && src_ready) f_sent <= f_sent + 4'd1;
  always @(posedge clk_dst) if (rst_dst_n && dst_valid && dst_ready) f_rcvd <= f_rcvd + 4'd1;

  always @(*) if (rst_src_n && src_valid && src_ready && f_sent == f_idx) assume(src_data == f_val);
  always @(*) if (rst_dst_n && dst_valid && f_rcvd == f_idx) assert(dst_data == f_val);

  // At most two words in flight: one in dst_q waiting for dst_ready, one in hold_q.
  wire [3:0] f_inflight = f_sent - f_rcvd;
  always @(*) assert(f_inflight <= 4'd2);

  // Source-side AXI-style stability: an offered word is not withdrawn by the design.
  // f_past_dst: $past() has no defined value before the first clk_dst edge.
  reg f_past_dst = 1'b0;
  always @(posedge clk_dst) f_past_dst <= 1'b1;
  always @(posedge clk_dst) if (f_past_dst && rst_dst_n && $past(rst_dst_n) && $past(dst_valid && !dst_ready)) begin
    assert(dst_valid);
    assert(dst_data == $past(dst_data));
  end

  always @(*) cover(f_rcvd == 4'd3);
`endif

endmodule
