// CDC checker test: one clk_a flop synchronized twice into clk_b. Expect PASS with WARNING divergent_sync.
module cdc_warn_divergent (input logic clk_a, clk_b, arst_n, d, output logic q0, q1);
  logic rst_a_n, rst_b_n, a_q;
  cdc_reset_sync u_ra (.clk(clk_a), .arst_n(arst_n), .rst_n(rst_a_n));
  cdc_reset_sync u_rb (.clk(clk_b), .arst_n(arst_n), .rst_n(rst_b_n));
  always_ff @(posedge clk_a or negedge rst_a_n) if (!rst_a_n) a_q <= 1'b0; else a_q <= d;
  cdc_sync_bit u_s0 (.clk_dst(clk_b), .rst_dst_n(rst_b_n), .d_async(a_q), .q(q0));
  cdc_sync_bit u_s1 (.clk_dst(clk_b), .rst_dst_n(rst_b_n), .d_async(a_q), .q(q1));
endmodule
