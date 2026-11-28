// cdc_sync_bit.sv -- N-flop synchronizer.
// Forge Feature 5 (timing-closure / clocking pack). Pack RTL, written for this pack;
// it is not Forge engine RTL.
//
// Use it for:
//   * a single-bit level signal (status, enable, toggle of a pulse/handshake), or
//   * a Gray-coded bus, bit by bit. That is only safe because at most one bit of a
//     Gray pointer changes per source update; formal/ proves that property for the
//     async FIFO, under the metastability model below.
// Never use it for a binary multi-bit bus (formal/ has a mutant that shows the failure).
//
// Rules (checked by tools/cdc_check.py on the yosys netlist):
//   * d_async must come straight from a flop in the source clock domain (no logic).
//   * STAGES >= 2 for the 250 MHz FPGA target; STAGES >= 3 for the 3 GHz ASIC track
//     (modelled MTBF sweep in docs/ASIC_3GHZ_MODELLED.md).
//   * ASYNC_REG: Vivado then places the chain close together, never packs it into an
//     SRL, and lists it as a synchronizer in report_cdc. yosys keeps the attribute for
//     the checker. shreg_extract="no" is a second guard against SRL packing.
module cdc_sync_bit #(
  parameter int unsigned WIDTH     = 1,
  parameter int unsigned STAGES    = 2,
  parameter bit          RESET_VAL = 1'b0
) (
  input  logic             clk_dst,
  input  logic             rst_dst_n,   // from cdc_reset_sync in the destination domain
  input  logic [WIDTH-1:0] d_async,     // flop output from the source domain
  output logic [WIDTH-1:0] q
);

  generate
    if (STAGES < 2) begin : g_bad_param
      // Deliberate elaboration error: a synchronizer needs at least two flops.
      cdc_sync_bit__STAGES_must_be_at_least_2 u_param_error ();
    end
  endgenerate

  (* ASYNC_REG = "TRUE", shreg_extract = "no", cdc_sync = "true" *)
  logic [STAGES*WIDTH-1:0] sync_q;
  logic [WIDTH-1:0]        stage0_d;

`ifdef FORMAL_META
  // Formal-only metastability model (multiclock proofs only).
  // clk2fflogic samples D one global step before the clock edge. A bit that changed in
  // that last step was changing inside the capture window, so it may resolve to either
  // its old or its new value (f_meta picks, freely, per bit and per edge). A bit that
  // was stable is captured correctly. The extra latency is bounded to one dst cycle.
  (* anyseq *) logic [WIDTH-1:0] f_meta;
  logic [WIDTH-1:0] f_d_prev;
  always @($global_clock) f_d_prev <= d_async;
  assign stage0_d = d_async ^ (f_meta & (d_async ^ f_d_prev));
`else
  assign stage0_d = d_async;
`endif

  always_ff @(posedge clk_dst or negedge rst_dst_n) begin
    if (!rst_dst_n) sync_q <= {(STAGES*WIDTH){RESET_VAL}};
    else            sync_q <= {sync_q[(STAGES-1)*WIDTH-1:0], stage0_d};
  end

  assign q = sync_q[STAGES*WIDTH-1 -: WIDTH];

endmodule
