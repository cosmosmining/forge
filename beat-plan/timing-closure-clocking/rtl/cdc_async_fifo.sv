// cdc_async_fifo.sv -- dual-clock FIFO with Gray-coded pointers and LUTRAM storage.
// Forge Feature 5 pack RTL (not Forge engine RTL).
//
// The stream crossing for the pack: host <-> core, memory <-> core, core <-> core
// across unrelated clocks. Structure (Cummings, SNUG 2002, "Simulation and Synthesis
// Techniques for Asynchronous FIFO Design"):
//   * binary + Gray pointer pairs, one extra wrap bit;
//   * only Gray pointers cross, through cdc_sync_bit (STAGES flops);
//   * full computed in the write domain, empty in the read domain, both registered
//     and both conservative (they can only be late to clear, never late to set).
// Storage is an asynchronous-read array, which maps to LUTRAM on AMD UltraScale+
// (RAM32M16 / RAM64M8). Read side is first-word-fall-through: rdata is valid whenever
// rempty is low; rinc pops. For a deep buffer (hundreds of entries), use a BRAM FIFO
// with a registered read instead (for example AMD xpm_fifo_async); not in this pack.
// rlevel / wfree are conservative counts for burst control (issue a burst of N only
// when rlevel >= N or wfree >= N): they may under-report by the synchronizer latency
// plus one cycle, never over-report. They are where Gray coding is load-bearing (see
// below). The converted pointer is registered before the subtraction: in the first
// ASAP7 3 GHz run the unregistered version (Gray->binary + subtract in one cycle) was
// the critical path, at -41/-48 ps (modelled, TT); see docs/ASIC_3GHZ_MODELLED.md.
//
// Formal: formal/async_fifo.sby proves, for every interleaving of the two clocks and
// with the metastability model in cdc_sync_bit, no overflow, no underflow, Gray
// pointers changing at most one bit per step, and data integrity (the word read at
// position p equals the word written at position p), and rlevel/wfree never
// over-report. Two mutants must FAIL: CDC_MUTANT_BINPTR (binary pointers cross) and
// CDC_MUTANT_FULL_NOINV (wrong full). Finding from the proofs: with binary pointers the
// registered, equality-compared full/empty flags alone stay safe (a one-cycle garbage
// pointer can enable only one extra push/pop, and the real pointer has just moved by
// one), but rlevel/wfree, which use the synchronized pointer as a number, break: the
// binary mutant fails on "rlevel never over-reports". Gray coding is what makes the
// synchronized pointer usable as a number.
//
// Reset: assert wrst_n and rrst_n together (one raw reset, one cdc_reset_sync per
// domain); release can be in any order. Resetting one side alone while the other side
// runs is not supported (the proof assumes the initial reset only).
module cdc_async_fifo #(
  parameter int unsigned WIDTH  = 32,
  parameter int unsigned DEPTH  = 16,   // power of two, >= 4
  parameter int unsigned STAGES = 2
) (
  input  logic             wclk,
  input  logic             wrst_n,
  input  logic             winc,     // push request; ignored while wfull
  input  logic [WIDTH-1:0] wdata,
  output logic             wfull,
  output logic [$clog2(DEPTH):0] wfree,   // slots certainly free (conservative)

  input  logic             rclk,
  input  logic             rrst_n,
  input  logic             rinc,     // pop request; ignored while rempty
  output logic [WIDTH-1:0] rdata,    // valid while !rempty
  output logic             rempty,
  output logic [$clog2(DEPTH):0] rlevel   // words certainly readable (conservative)
);

  localparam int unsigned AW = $clog2(DEPTH);

  // b[i] = XOR of g[AW:i], written as an independent reduction per bit so synthesis
  // builds log-depth XOR trees instead of one ripple chain (3 GHz track).
  // Verilog-2001 style: yosys has no `return`.
  function automatic [AW:0] gray2bin(input [AW:0] g);
    reg [AW:0] b;
    integer i;
    begin
      for (i = 0; i <= AW; i = i + 1) b[i] = ^(g >> i);
      gray2bin = b;
    end
  endfunction

  generate
    if (DEPTH < 4 || (1 << AW) != DEPTH) begin : g_bad_param
      cdc_async_fifo__DEPTH_must_be_power_of_2_and_at_least_4 u_param_error ();
    end
  endgenerate

  // Storage: written in wclk, read asynchronously by the read pointer. An entry is
  // read only after the synchronized write pointer shows it was written.
  (* ram_style = "distributed" *)
  logic [WIDTH-1:0] mem [0:DEPTH-1];

  // ------------------------------ write domain -------------------------------
  logic [AW:0] wbin, wbin_nxt, wgray_nxt;
  (* cdc_gray = "true" *) logic [AW:0] wgray;
  logic [AW:0] wq2_rptr;      // read pointer seen in wclk (Gray, or binary in mutant)
  logic        wpush;

  assign wpush     = winc && !wfull;
  assign wbin_nxt  = wbin + {{AW{1'b0}}, wpush};
  assign wgray_nxt = (wbin_nxt >> 1) ^ wbin_nxt;

  logic [AW:0] wq2_rbin;      // synchronized read pointer as a binary number
  logic [AW:0] wq2_rbin_q;    // ...registered (timing: one more cycle, still conservative)
`ifdef CDC_MUTANT_BINPTR
  assign wq2_rbin = wq2_rptr;
`else
  assign wq2_rbin = gray2bin(wq2_rptr);
`endif

  always_ff @(posedge wclk or negedge wrst_n) begin
    if (!wrst_n) begin
      wbin  <= '0;
      wgray <= '0;
      wfull <= 1'b0;
      wfree <= DEPTH[AW:0];
      wq2_rbin_q <= '0;
    end else begin
      wbin  <= wbin_nxt;
      wgray <= wgray_nxt;
      wq2_rbin_q <= wq2_rbin;
      // DEPTH - (wbin_nxt - wq2_rbin_q), as one multi-operand sum
      wfree <= DEPTH[AW:0] - wbin - {{AW{1'b0}}, wpush} + wq2_rbin_q;
`ifdef CDC_MUTANT_BINPTR
      wfull <= (wbin_nxt == {~wq2_rptr[AW], wq2_rptr[AW-1:0]});
`elsif CDC_MUTANT_FULL_NOINV
      wfull <= (wgray_nxt == wq2_rptr);
`else
      // Full: Gray of (rptr + DEPTH) = rgray with its two MSBs inverted.
      wfull <= (wgray_nxt == {~wq2_rptr[AW:AW-1], wq2_rptr[AW-2:0]});
`endif
    end
  end

  always_ff @(posedge wclk) begin
    if (wpush) mem[wbin[AW-1:0]] <= wdata;
  end

  // ------------------------------- read domain -------------------------------
  logic [AW:0] rbin, rbin_nxt, rgray_nxt;
  (* cdc_gray = "true" *) logic [AW:0] rgray;
  logic [AW:0] rq2_wptr;      // write pointer seen in rclk
  logic        rpop;

  assign rpop      = rinc && !rempty;
  assign rbin_nxt  = rbin + {{AW{1'b0}}, rpop};
  assign rgray_nxt = (rbin_nxt >> 1) ^ rbin_nxt;

  logic [AW:0] rq2_wbin;      // synchronized write pointer as a binary number
  logic [AW:0] rq2_wbin_q;    // ...registered (timing: one more cycle, still conservative)
`ifdef CDC_MUTANT_BINPTR
  assign rq2_wbin = rq2_wptr;
`else
  assign rq2_wbin = gray2bin(rq2_wptr);
`endif

  always_ff @(posedge rclk or negedge rrst_n) begin
    if (!rrst_n) begin
      rbin   <= '0;
      rgray  <= '0;
      rempty <= 1'b1;
      rlevel <= '0;
      rq2_wbin_q <= '0;
    end else begin
      rbin   <= rbin_nxt;
      rgray  <= rgray_nxt;
      rq2_wbin_q <= rq2_wbin;
      // rq2_wbin_q - rbin_nxt, as one multi-operand sum
      rlevel <= rq2_wbin_q - rbin - {{AW{1'b0}}, rpop};
`ifdef CDC_MUTANT_BINPTR
      rempty <= (rbin_nxt == rq2_wptr);
`else
      rempty <= (rgray_nxt == rq2_wptr);
`endif
    end
  end

  assign rdata = mem[rbin[AW-1:0]];

  // ------------------------------ pointer crossings ----------------------------
`ifdef CDC_MUTANT_BINPTR
  // Test-only mutation: cross the BINARY pointers (wrong). Must fail formal.
  cdc_sync_bit #(.WIDTH(AW+1), .STAGES(STAGES)) u_wptr_sync (
    .clk_dst(rclk), .rst_dst_n(rrst_n), .d_async(wbin), .q(rq2_wptr));
  cdc_sync_bit #(.WIDTH(AW+1), .STAGES(STAGES)) u_rptr_sync (
    .clk_dst(wclk), .rst_dst_n(wrst_n), .d_async(rbin), .q(wq2_rptr));
`else
  cdc_sync_bit #(.WIDTH(AW+1), .STAGES(STAGES)) u_wptr_sync (
    .clk_dst(rclk), .rst_dst_n(rrst_n), .d_async(wgray), .q(rq2_wptr));
  cdc_sync_bit #(.WIDTH(AW+1), .STAGES(STAGES)) u_rptr_sync (
    .clk_dst(wclk), .rst_dst_n(wrst_n), .d_async(rgray), .q(wq2_rptr));
`endif

`ifdef FORMAL
  // ---- environment: both resets held for the first two global steps, never again ----
  reg [1:0] f_gstep = 2'd0;
  always @($global_clock) if (f_gstep != 2'd3) f_gstep <= f_gstep + 2'd1;
  always @(*) if (f_gstep < 2'd2) begin assume(!wrst_n); assume(!rrst_n); end
  always @($global_clock) if (f_gstep != 2'd0) begin
    if ($past(wrst_n)) assume(wrst_n);
    if ($past(rrst_n)) assume(rrst_n);
  end

  // ---- occupancy ----
  wire [AW:0] f_fill = wbin - rbin;            // modulo 2^(AW+1)

  always @(*) begin
    assert(wgray == ((wbin >> 1) ^ wbin));
    assert(rgray == ((rbin >> 1) ^ rbin));
    assert(f_fill <= DEPTH);                   // never more than DEPTH entries
    if (wrst_n && f_fill == DEPTH) assert(wfull);    // no overflow possible
    if (rrst_n && f_fill == 0)     assert(rempty);   // no underflow possible
    // burst-control counts never over-report
    if (rrst_n) assert(rlevel <= f_fill);
    if (wrst_n) assert({1'b0, wfree} + {1'b0, f_fill} <= DEPTH);
  end

  // Gray pointers change at most one bit per global step: this is what makes the
  // per-bit synchronizers safe, whatever way each bit resolves.
  always @($global_clock) if (f_gstep != 2'd0) begin
    assert($onehot0(wgray ^ $past(wgray)));
    assert($onehot0(rgray ^ $past(rgray)));
  end

  // ---- data integrity for an arbitrary pointer value ----
  (* anyconst *) logic [AW:0]      f_ptr;
  (* anyconst *) logic [WIDTH-1:0] f_val;
  always @(*) if (wrst_n && wpush && wbin == f_ptr) assume(wdata == f_val);

  wire f_live = ((f_ptr - rbin) < f_fill);   // entry f_ptr is written and not yet read
  always @(*) if (f_live) assert(mem[f_ptr[AW-1:0]] == f_val);
  always @(*) if (rrst_n && !rempty && rbin == f_ptr) assert(rdata == f_val);

  // ---- reachability ----
  reg f_was_full = 1'b0;
  always @($global_clock) if (wfull) f_was_full <= 1'b1;
  always @(*) cover(wfull);
  always @(*) cover(f_was_full && rempty && rrst_n && f_fill == 0);
`endif

endmodule
