// CDC checker test: two clk_a flops ANDed in front of a synchronizer. Expect ERROR logic_before_sync.
module cdc_neg_logic_before_sync (input logic clk_a, clk_b, arst_n, d0, d1, output logic q);
  logic rst_a_n, rst_b_n, a0_q, a1_q;
  cdc_reset_sync u_ra (.clk(clk_a), .arst_n(arst_n), .rst_n(rst_a_n));
  cdc_reset_sync u_rb (.clk(clk_b), .arst_n(arst_n), .rst_n(rst_b_n));
  always_ff @(posedge clk_a or negedge rst_a_n) if (!rst_a_n) begin a0_q <= 1'b0; a1_q <= 1'b0; end else begin a0_q <= d0; a1_q <= d1; end
  cdc_sync_bit u_s (.clk_dst(clk_b), .rst_dst_n(rst_b_n), .d_async(a0_q & a1_q), .q(q));
endmodule
