// cdc_reset_sync.sv -- reset bridge: asserts asynchronously, deasserts synchronously.
// Forge Feature 5 pack RTL (not Forge engine RTL).
//
// One instance per clock domain. Every flop in that domain takes rst_n from here, so
// reset release never violates recovery/removal timing in that domain.
// The raw reset (arst_n) can come from anywhere: a pin, a PLL/MMCM "locked" output, or a
// software reset register in another domain.
module cdc_reset_sync #(
  parameter int unsigned STAGES = 2
) (
  input  logic clk,
  input  logic arst_n,   // raw asynchronous reset, active low
  output logic rst_n     // asserts with arst_n, deasserts STAGES clk edges after it
);

  generate
    if (STAGES < 2) begin : g_bad_param
      cdc_reset_sync__STAGES_must_be_at_least_2 u_param_error ();
    end
  endgenerate

  // r[STAGES-1] drives async resets downstream while r[STAGES-2] feeds it synchronously:
  // that is the reset-bridge pattern, so Verilator's SYNCASYNCNET is expected here.
  /* verilator lint_off SYNCASYNCNET */
  (* ASYNC_REG = "TRUE", shreg_extract = "no", cdc_reset_sync = "true" *)
  logic [STAGES-1:0] r;
  /* verilator lint_on SYNCASYNCNET */

  always_ff @(posedge clk or negedge arst_n) begin
    if (!arst_n) r <= '0;
    else         r <= {r[STAGES-2:0], 1'b1};
  end

  assign rst_n = r[STAGES-1];

endmodule
