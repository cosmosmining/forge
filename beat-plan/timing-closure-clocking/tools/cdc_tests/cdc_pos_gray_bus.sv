// CDC checker test: the same counter, Gray-coded and marked cdc_gray. Expect PASS.
module cdc_pos_gray_bus (input logic clk_a, clk_b, arst_n, output logic [3:0] q);
  logic rst_a_n, rst_b_n;
  logic [3:0] cnt_q;
  (* cdc_gray = "true" *) logic [3:0] gray_q;
  cdc_reset_sync u_ra (.clk(clk_a), .arst_n(arst_n), .rst_n(rst_a_n));
  cdc_reset_sync u_rb (.clk(clk_b), .arst_n(arst_n), .rst_n(rst_b_n));
  always_ff @(posedge clk_a or negedge rst_a_n)
    if (!rst_a_n) begin cnt_q <= '0; gray_q <= '0; end
    else begin cnt_q <= cnt_q + 4'd1; gray_q <= (cnt_q + 4'd1) ^ ((cnt_q + 4'd1) >> 1); end
  cdc_sync_bit #(.WIDTH(4)) u_s (.clk_dst(clk_b), .rst_dst_n(rst_b_n), .d_async(gray_q), .q(q));
endmodule
