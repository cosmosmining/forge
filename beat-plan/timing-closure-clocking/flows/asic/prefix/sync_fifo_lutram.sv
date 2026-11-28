// PRE-FIX VERSION, kept only to reproduce the before/after 3 GHz timing comparison in
// docs/ASIC_3GHZ_MODELLED.md (flows/run_asic_modelled.sh). Do not use; rtl/ has the fix.
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
  logic        do_push, do_pop;

  assign count   = wptr - rptr;
  assign empty   = (wptr == rptr);
  assign full    = (wptr == {~rptr[AW], rptr[AW-1:0]});
  assign do_push = push && !full;
  assign do_pop  = pop  && !empty;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wptr <= '0;
      rptr <= '0;
    end else begin
      if (do_push) wptr <= wptr + 1'b1;
      if (do_pop)  rptr <= rptr + 1'b1;
    end
  end

  always_ff @(posedge clk) begin
    if (do_push) mem[wptr[AW-1:0]] <= wdata;
  end

  assign rdata = mem[rptr[AW-1:0]];

endmodule
