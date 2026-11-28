// CDC checker test: a flop in clk_b samples a clk_a flop directly. Expect ERROR unsynchronized.
module cdc_neg_unsync (input logic clk_a, clk_b, arst_n, d, output logic q);
  logic rst_a_n, rst_b_n, a_q, b_q;
  cdc_reset_sync u_ra (.clk(clk_a), .arst_n(arst_n), .rst_n(rst_a_n));
  cdc_reset_sync u_rb (.clk(clk_b), .arst_n(arst_n), .rst_n(rst_b_n));
  always_ff @(posedge clk_a or negedge rst_a_n) if (!rst_a_n) a_q <= 1'b0; else a_q <= d;
  always_ff @(posedge clk_b or negedge rst_b_n) if (!rst_b_n) b_q <= 1'b0; else b_q <= a_q;
  assign q = b_q;
endmodule
