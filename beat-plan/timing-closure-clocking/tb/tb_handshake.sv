// tb_handshake.sv -- randomized two-clock test of cdc_handshake (icarus, -g2012).
// Pass criteria: words arrive exactly once, in order, unchanged; dst_valid/dst_data hold
// steady while not taken; all N words delivered.
`timescale 1ps/1ps
// Non-negative random number in [0, m), drawn from seed variable s.
`define RND(s, m) (($random(s) & 32'h7fffffff) % (m))
module tb_handshake;
  parameter int WIDTH  = 24;
  parameter int STAGES = 2;
  localparam int SBSZ  = 1 << 14;

  integer seed_s, seed_d, seed_c1, seed_c2;
  integer shalf, dhalf, jit, n_words, valid_pct, ready_pct;

  logic clk_src = 1'b0, clk_dst = 1'b0, arst_n = 1'b0;
  logic rst_src_n, rst_dst_n;
  logic src_valid = 1'b0, dst_ready = 1'b0;
  logic [WIDTH-1:0] src_data = '0;
  logic src_ready, dst_valid;
  logic [WIDTH-1:0] dst_data;

  cdc_reset_sync u_srs (.clk(clk_src), .arst_n(arst_n), .rst_n(rst_src_n));
  cdc_reset_sync u_drs (.clk(clk_dst), .arst_n(arst_n), .rst_n(rst_dst_n));

  cdc_handshake #(.WIDTH(WIDTH), .STAGES(STAGES)) dut (
    .clk_src(clk_src), .rst_src_n(rst_src_n), .src_valid(src_valid), .src_ready(src_ready), .src_data(src_data),
    .clk_dst(clk_dst), .rst_dst_n(rst_dst_n), .dst_valid(dst_valid), .dst_ready(dst_ready), .dst_data(dst_data));

  logic [WIDTH-1:0] sb [0:SBSZ-1];
  integer sent = 0, rcvd = 0, errors = 0;
  logic             held_valid = 1'b0;
  logic [WIDTH-1:0] held_data  = '0;


  initial begin
    if (!$value$plusargs("SEED=%d", seed_s)) seed_s = 1;
    seed_d = seed_s * 7 + 3; seed_c1 = seed_s * 13 + 5; seed_c2 = seed_s * 17 + 11;
    if (!$value$plusargs("SHALF=%d", shalf))  shalf = 1000;
    if (!$value$plusargs("DHALF=%d", dhalf))  dhalf = 1700;
    if (!$value$plusargs("JIT=%d", jit))      jit = 40;
    if (!$value$plusargs("N=%d", n_words))    n_words = 1500;
    if (!$value$plusargs("VALID=%d", valid_pct)) valid_pct = 70;
    if (!$value$plusargs("READY=%d", ready_pct)) ready_pct = 60;
  end

  initial forever begin #(shalf + `RND(seed_c1, jit)) clk_src = ~clk_src; end
  initial forever begin #(dhalf + `RND(seed_c2, jit)) clk_dst = ~clk_dst; end
  initial #(7 * (shalf + dhalf)) arst_n = 1'b1;

  // Source: hold valid+data until accepted (valid/ready rule), then maybe pick new.
  always @(negedge clk_src) begin
    if (!rst_src_n) begin
      src_valid <= 1'b0;
    end else if (!src_valid && sent < n_words && `RND(seed_s, 100) < valid_pct) begin
      src_valid <= 1'b1;
      src_data  <= WIDTH'($random(seed_s));
    end
  end
  always @(posedge clk_src) begin
    if (rst_src_n && src_valid && src_ready) begin
      sb[sent % SBSZ] = src_data;
      sent = sent + 1;
      src_valid <= 1'b0;     // offer the next word from the next negedge
    end
  end

  always @(negedge clk_dst) dst_ready <= rst_dst_n && (`RND(seed_d, 100) < ready_pct);

  always @(posedge clk_dst) begin
    if (rst_dst_n) begin
      if (held_valid && (!dst_valid || dst_data !== held_data)) begin
        errors = errors + 1;
        $display("ERROR t=%0t offered word withdrawn or changed", $time);
      end
      if (dst_valid && dst_ready) begin
        if (rcvd >= sent) begin
          errors = errors + 1; $display("ERROR t=%0t word delivered that was never sent", $time);
        end else if (dst_data !== sb[rcvd % SBSZ]) begin
          errors = errors + 1;
          $display("ERROR t=%0t word %0d got %h expected %h", $time, rcvd, dst_data, sb[rcvd % SBSZ]);
        end
        rcvd = rcvd + 1;
      end
      held_valid = dst_valid && !dst_ready;
      held_data  = dst_data;
    end
  end

  initial begin : finish
    wait (sent >= n_words);
    repeat (200) @(posedge clk_dst);
    if (rcvd != n_words) begin errors = errors + 1; $display("ERROR delivered %0d of %0d", rcvd, n_words); end
    if (errors == 0)
      $display("TB_RESULT PASS tb_handshake STAGES=%0d SHALF=%0d DHALF=%0d words=%0d", STAGES, shalf, dhalf, rcvd);
    else
      $display("TB_RESULT FAIL tb_handshake errors=%0d", errors);
    $finish;
  end

  initial begin
    #(64'd2_000_000_000);
    $display("TB_RESULT FAIL tb_handshake timeout sent=%0d rcvd=%0d", sent, rcvd);
    $finish;
  end
endmodule
