// CDC checker test: a 4-bit binary counter crosses through bit synchronizers. Expect ERROR multibit_not_gray.
module cdc_neg_binary_bus (input logic clk_a, clk_b, arst_n, output logic [3:0] q);
  logic rst_a_n, rst_b_n;
  logic [3:0] cnt_q;
  cdc_reset_sync u_ra (.clk(clk_a), .arst_n(arst_n), .rst_n(rst_a_n));
  cdc_reset_sync u_rb (.clk(clk_b), .arst_n(arst_n), .rst_n(rst_b_n));
  always_ff @(posedge clk_a or negedge rst_a_n) if (!rst_a_n) cnt_q <= '0; else cnt_q <= cnt_q + 4'd1;
  cdc_sync_bit #(.WIDTH(4)) u_s (.clk_dst(clk_b), .rst_dst_n(rst_b_n), .d_async(cnt_q), .q(q));
endmodule
