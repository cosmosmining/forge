// CDC checker test: a clk_b flop uses the raw reset pin directly. Expect ERROR reset_not_bridged.
module cdc_neg_raw_reset (input logic clk_b, arst_n, d, output logic q);
  always_ff @(posedge clk_b or negedge arst_n) if (!arst_n) q <= 1'b0; else q <= d;
endmodule
