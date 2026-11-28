// CDC checker test: a single ASYNC_REG flop used as a "synchronizer". Expect ERROR sync_too_short.
module cdc_neg_short_sync (input logic clk_a, clk_b, arst_n, d, output logic q);
  logic rst_a_n, rst_b_n, a_q;
  (* ASYNC_REG = "TRUE" *) logic s_q;
  cdc_reset_sync u_ra (.clk(clk_a), .arst_n(arst_n), .rst_n(rst_a_n));
  cdc_reset_sync u_rb (.clk(clk_b), .arst_n(arst_n), .rst_n(rst_b_n));
  always_ff @(posedge clk_a or negedge rst_a_n) if (!rst_a_n) a_q <= 1'b0; else a_q <= d;
  always_ff @(posedge clk_b or negedge rst_b_n) if (!rst_b_n) s_q <= 1'b0; else s_q <= a_q;
  assign q = s_q;
endmodule
