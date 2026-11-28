// CDC checker test: a clk_b flop is reset by the clk_a reset bridge. Expect ERROR reset_not_bridged.
module cdc_neg_reset_cross (input logic clk_a, clk_b, arst_n, d, output logic q);
  logic rst_a_n;
  cdc_reset_sync u_ra (.clk(clk_a), .arst_n(arst_n), .rst_n(rst_a_n));
  always_ff @(posedge clk_b or negedge rst_a_n) if (!rst_a_n) q <= 1'b0; else q <= d;
endmodule
