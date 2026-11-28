// sync_stage.v -- one synchronizer stage, two ways, in ASAP7 RVT cells (gate level).
// Forge Feature 5. Used by flows/asic/sync_stage.tcl for the MODELLED MTBF budget.
//   a: what yosys maps cdc_sync_bit to with ASAP7 (the only async-reset flop,
//      DFFASRHQNx1, has an inverted output, so an INVx1 sits between stages);
//   b: QN wired straight to the next D (the chain stores alternating polarity and the
//      output polarity is fixed up after the last stage): no gate in the stage path.
module sync_stage (
  input  clk,
  input  rst_n,
  input  d,
  output qa,
  output qb
);
  wire a0_qn, a1_d, a1_qn, b0_qn, b1_qn;
  DFFASRHQNx1_ASAP7_75t_R a0 (.CLK(clk), .D(d),     .QN(a0_qn), .RESETN(rst_n), .SETN(1'b1));
  INVx1_ASAP7_75t_R       ai (.A(a0_qn), .Y(a1_d));
  DFFASRHQNx1_ASAP7_75t_R a1 (.CLK(clk), .D(a1_d),  .QN(a1_qn), .RESETN(rst_n), .SETN(1'b1));
  DFFASRHQNx1_ASAP7_75t_R b0 (.CLK(clk), .D(d),     .QN(b0_qn), .RESETN(rst_n), .SETN(1'b1));
  DFFASRHQNx1_ASAP7_75t_R b1 (.CLK(clk), .D(b0_qn), .QN(b1_qn), .RESETN(rst_n), .SETN(1'b1));
  assign qa = a1_qn;
  assign qb = b1_qn;
endmodule
