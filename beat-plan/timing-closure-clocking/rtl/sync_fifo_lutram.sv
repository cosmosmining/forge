// sync_fifo_lutram.sv -- single-clock first-word-fall-through FIFO in LUTRAM.
// Forge Feature 5 pack RTL (not Forge engine RTL).
//
// Small buffers (8..64 entries): skid space at the end of an SLR crossing, elastic
// buffers between pipeline stages. The array has an asynchronous read, so on AMD
// UltraScale+ it maps to distributed RAM (RAM32M16 / RAM64M8), not BRAM and not FFs.
// push while full and pop while empty are ignored. A caller that must never lose a
// word (slr_crossing) proves in formal that it never pushes while full.
module sync_fifo_lutram #(
  parameter int unsigned WIDTH = 32,
  parameter int unsigned DEPTH = 16                    // power of two, >= 2
) (
  input  logic                     clk,
  input  logic                     rst_n,
  input  logic                     push,
  input  logic [WIDTH-1:0]         wdata,
  input  logic                     pop,
  output logic [WIDTH-1:0]         rdata,              // valid while !empty
  output logic                     empty,
  output logic                     full,
  output logic [$clog2(DEPTH):0]   count
);

  localparam int unsigned AW = $clog2(DEPTH);

  generate
    if (DEPTH < 2 || (1 << AW) != DEPTH) begin : g_bad_param
      sync_fifo_lutram__DEPTH_must_be_power_of_2_and_at_least_2 u_param_error ();
    end
  endgenerate

  (* ram_style = "distributed" *)
  logic [WIDTH-1:0] mem [0:DEPTH-1];

  logic [AW:0] wptr, rptr;           // one extra wrap bit
  logic [AW:0] wptr_nxt, rptr_nxt;
  logic [AW:0] count_q;
  logic        empty_q, full_q;
  logic        do_push, do_pop;

  // Flags and count are registered, computed from the next-state pointers, so the
  // write path starts at a flop (full_q) instead of a pointer compare. Same values as
  // the combinational version, one compare shorter. Done for the 3 GHz track: in the
  // first ASAP7 run the combinational full was on slr_crossing's critical path at
  // -48 ps (modelled, TT); see docs/ASIC_3GHZ_MODELLED.md.
  assign do_push  = push && !full_q;
  assign do_pop   = pop  && !empty_q;
  assign wptr_nxt = wptr + {{AW{1'b0}}, do_push};
  assign rptr_nxt = rptr + {{AW{1'b0}}, do_pop};
  assign empty    = empty_q;
  assign full     = full_q;
  assign count    = count_q;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wptr    <= '0;
      rptr    <= '0;
      count_q <= '0;
      empty_q <= 1'b1;
      full_q  <= 1'b0;
    end else begin
      wptr    <= wptr_nxt;
      rptr    <= rptr_nxt;
      count_q <= count_q + {{AW{1'b0}}, do_push} - {{AW{1'b0}}, do_pop};
      empty_q <= (wptr_nxt == rptr_nxt);
      full_q  <= (wptr_nxt == {~rptr_nxt[AW], rptr_nxt[AW-1:0]});
    end
  end

  always_ff @(posedge clk) begin
    if (do_push) mem[wptr[AW-1:0]] <= wdata;
  end

  assign rdata = mem[rptr[AW-1:0]];

endmodule
