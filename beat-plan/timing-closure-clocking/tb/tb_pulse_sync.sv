// tb_pulse_sync.sv -- randomized two-clock test of cdc_pulse_sync (icarus, -g2012).
// The source pulses at random, including while busy. Pass criteria: the number of
// destination pulses equals the number of accepted source pulses (src_accept), each
// destination pulse is one cycle wide, and some pulses were refused while busy (so
// the busy path was exercised).
`timescale 1ps/1ps
// Non-negative random number in [0, m), drawn from seed variable s.
`define RND(s, m) (($random(s) & 32'h7fffffff) % (m))
module tb_pulse_sync;
  parameter int STAGES = 2;

  integer seed_s, seed_c1, seed_c2;
  integer shalf, dhalf, jit, n_pulses, pulse_pct;

  logic clk_src = 1'b0, clk_dst = 1'b0, arst_n = 1'b0;
  logic rst_src_n, rst_dst_n;
  logic src_pulse = 1'b0;
  logic src_busy, src_accept, dst_pulse;

  cdc_reset_sync u_srs (.clk(clk_src), .arst_n(arst_n), .rst_n(rst_src_n));
  cdc_reset_sync u_drs (.clk(clk_dst), .arst_n(arst_n), .rst_n(rst_dst_n));

  cdc_pulse_sync #(.STAGES(STAGES)) dut (
    .clk_src(clk_src), .rst_src_n(rst_src_n), .src_pulse(src_pulse), .src_busy(src_busy), .src_accept(src_accept),
    .clk_dst(clk_dst), .rst_dst_n(rst_dst_n), .dst_pulse(dst_pulse));

  integer accepted = 0, refused = 0, delivered = 0, errors = 0;
  logic   last_dst_pulse = 1'b0;


  initial begin
    if (!$value$plusargs("SEED=%d", seed_s)) seed_s = 1;
    seed_c1 = seed_s * 13 + 5; seed_c2 = seed_s * 17 + 11;
    if (!$value$plusargs("SHALF=%d", shalf))  shalf = 1000;
    if (!$value$plusargs("DHALF=%d", dhalf))  dhalf = 2300;
    if (!$value$plusargs("JIT=%d", jit))      jit = 40;
    if (!$value$plusargs("N=%d", n_pulses))   n_pulses = 800;
    if (!$value$plusargs("PULSE=%d", pulse_pct)) pulse_pct = 30;
  end

  initial forever begin #(shalf + `RND(seed_c1, jit)) clk_src = ~clk_src; end
  initial forever begin #(dhalf + `RND(seed_c2, jit)) clk_dst = ~clk_dst; end
  initial #(7 * (shalf + dhalf)) arst_n = 1'b1;

  always @(negedge clk_src) src_pulse <= rst_src_n && (accepted < n_pulses) && (`RND(seed_s, 100) < pulse_pct);

  always @(posedge clk_src) if (rst_src_n && src_pulse) begin
    if (src_accept) accepted = accepted + 1;
    else            refused  = refused + 1;
  end

  always @(posedge clk_dst) if (rst_dst_n) begin
    if (dst_pulse) begin
      delivered = delivered + 1;
      if (last_dst_pulse) begin errors = errors + 1; $display("ERROR t=%0t dst_pulse wider than one cycle", $time); end
      if (delivered > accepted) begin errors = errors + 1; $display("ERROR t=%0t more pulses delivered than accepted", $time); end
    end
    last_dst_pulse = dst_pulse;
  end

  initial begin : finish
    wait (accepted >= n_pulses);
    repeat (50) @(posedge clk_dst);
    if (delivered != accepted) begin errors = errors + 1; $display("ERROR accepted %0d delivered %0d", accepted, delivered); end
    if (refused == 0)          begin errors = errors + 1; $display("ERROR busy path never exercised"); end
    if (errors == 0)
      $display("TB_RESULT PASS tb_pulse_sync STAGES=%0d SHALF=%0d DHALF=%0d accepted=%0d refused_while_busy=%0d", STAGES, shalf, dhalf, accepted, refused);
    else
      $display("TB_RESULT FAIL tb_pulse_sync errors=%0d", errors);
    $finish;
  end

  initial begin
    #(64'd2_000_000_000);
    $display("TB_RESULT FAIL tb_pulse_sync timeout");
    $finish;
  end
endmodule
