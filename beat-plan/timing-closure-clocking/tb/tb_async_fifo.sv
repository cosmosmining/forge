// tb_async_fifo.sv -- randomized two-clock test of cdc_async_fifo (icarus, -g2012).
// Clocks: independent half periods (+WHALF, +RHALF, in ps) with random jitter (+JIT).
// Pass criteria: every word read equals the next word written (scoreboard), no read
// while the scoreboard is empty, never more than DEPTH words held, all N words drained,
// and both wfull and rempty were actually exercised.
`timescale 1ps/1ps
// Non-negative random number in [0, m), drawn from seed variable s.
`define RND(s, m) (($random(s) & 32'h7fffffff) % (m))
module tb_async_fifo;
  parameter int WIDTH  = 16;
  parameter int DEPTH  = 8;
  parameter int STAGES = 2;
  localparam int SBSZ  = 1 << 16;

  integer seed_w, seed_r, seed_c1, seed_c2;
  integer whalf, rhalf, jit, n_words, push_pct, pop_pct;

  logic wclk = 1'b0, rclk = 1'b0;
  logic arst_n = 1'b0;
  logic wrst_n, rrst_n;
  logic winc = 1'b0, rinc = 1'b0;
  logic [WIDTH-1:0] wdata = '0;
  logic [WIDTH-1:0] rdata;
  logic wfull, rempty;
  logic [$clog2(DEPTH):0] wfree, rlevel;

  // One raw reset, one reset bridge per domain (the pack's reset rule).
  cdc_reset_sync #(.STAGES(2)) u_wrs (.clk(wclk), .arst_n(arst_n), .rst_n(wrst_n));
  cdc_reset_sync #(.STAGES(2)) u_rrs (.clk(rclk), .arst_n(arst_n), .rst_n(rrst_n));

  cdc_async_fifo #(.WIDTH(WIDTH), .DEPTH(DEPTH), .STAGES(STAGES)) dut (
    .wclk(wclk), .wrst_n(wrst_n), .winc(winc), .wdata(wdata), .wfull(wfull), .wfree(wfree),
    .rclk(rclk), .rrst_n(rrst_n), .rinc(rinc), .rdata(rdata), .rempty(rempty), .rlevel(rlevel));

  logic [WIDTH-1:0] sb [0:SBSZ-1];
  integer wr_idx = 0, rd_idx = 0, errors = 0;
  integer n_full = 0, n_empty_after_data = 0, max_held = 0, max_rlevel = 0, max_wfree_seen = 0;
  bit drain = 1'b0;


  initial begin
    if (!$value$plusargs("SEED=%d", seed_w)) seed_w = 1;
    seed_r = seed_w * 7 + 3; seed_c1 = seed_w * 13 + 5; seed_c2 = seed_w * 17 + 11;
    if (!$value$plusargs("WHALF=%d", whalf))   whalf = 1000;
    if (!$value$plusargs("RHALF=%d", rhalf))   rhalf = 1550;
    if (!$value$plusargs("JIT=%d", jit))       jit = 50;
    if (!$value$plusargs("N=%d", n_words))     n_words = 5000;
    if (!$value$plusargs("PUSH=%d", push_pct)) push_pct = 80;
    if (!$value$plusargs("POP=%d", pop_pct))   pop_pct = 50;
  end

  initial forever begin #(whalf + `RND(seed_c1, jit)) wclk = ~wclk; end
  initial forever begin #(rhalf + `RND(seed_c2, jit)) rclk = ~rclk; end

  initial begin
    #(7 * (whalf + rhalf)) arst_n = 1'b1;
  end

  // ---- writer: drive on negedge, account on posedge ----
  always @(negedge wclk) begin
    if (wrst_n && wr_idx < n_words) begin
      winc  <= (`RND(seed_w, 100) < push_pct);
      wdata <= WIDTH'($random(seed_w));
    end else begin
      winc <= 1'b0;
    end
  end

  always @(posedge wclk) begin
    // wfree must never promise more free slots than really exist
    if (wrst_n && wfree > DEPTH - (wr_idx - rd_idx)) begin
      errors = errors + 1;
      $display("ERROR t=%0t wfree=%0d over-reports (free=%0d)", $time, wfree, DEPTH - (wr_idx - rd_idx));
    end
    if (wrst_n && wfree > max_wfree_seen) max_wfree_seen = wfree;
    if (wrst_n && winc && !wfull) begin
      sb[wr_idx % SBSZ] = wdata;
      wr_idx = wr_idx + 1;
      if (wr_idx - rd_idx > DEPTH) begin
        errors = errors + 1;
        $display("ERROR t=%0t overflow: %0d words held, DEPTH=%0d", $time, wr_idx - rd_idx, DEPTH);
      end
      if (wr_idx - rd_idx > max_held) max_held = wr_idx - rd_idx;
    end
    if (wrst_n && wfull) n_full = n_full + 1;
  end

  // ---- reader ----
  always @(negedge rclk) begin
    if (rrst_n) rinc <= drain ? 1'b1 : (`RND(seed_r, 100) < pop_pct);
    else        rinc <= 1'b0;
  end

  always @(posedge rclk) begin
    // rlevel must never promise more words than were really written
    if (rrst_n && rlevel > wr_idx - rd_idx) begin
      errors = errors + 1;
      $display("ERROR t=%0t rlevel=%0d over-reports (held=%0d)", $time, rlevel, wr_idx - rd_idx);
    end
    if (rrst_n && rlevel > max_rlevel) max_rlevel = rlevel;
    if (rrst_n && !rempty) begin
      if (rd_idx >= wr_idx) begin
        errors = errors + 1;
        $display("ERROR t=%0t underflow: rempty low with no word written", $time);
      end else if (rinc) begin
        if (rdata !== sb[rd_idx % SBSZ]) begin
          errors = errors + 1;
          $display("ERROR t=%0t word %0d: got %h expected %h", $time, rd_idx, rdata, sb[rd_idx % SBSZ]);
        end
        rd_idx = rd_idx + 1;
      end
    end
    if (rrst_n && rempty && rd_idx > 0) n_empty_after_data = n_empty_after_data + 1;
  end

  initial begin : finish
    integer guard;
    wait (wr_idx >= n_words);
    drain = 1'b1;
    guard = 0;
    while (rd_idx < wr_idx && guard < 100000) begin
      @(posedge rclk); guard = guard + 1;
    end
    repeat (20) @(posedge rclk);
    if (rd_idx != n_words) begin
      errors = errors + 1;
      $display("ERROR drained %0d of %0d words", rd_idx, n_words);
    end
    if (n_full == 0)             begin errors = errors + 1; $display("ERROR wfull never asserted (test too weak)"); end
    if (n_empty_after_data == 0) begin errors = errors + 1; $display("ERROR rempty never re-asserted (test too weak)"); end
    if (2 * max_rlevel < DEPTH)  begin errors = errors + 1; $display("ERROR rlevel never reached DEPTH/2 (max %0d)", max_rlevel); end
    if (errors == 0)
      $display("TB_RESULT PASS tb_async_fifo DEPTH=%0d STAGES=%0d WHALF=%0d RHALF=%0d JIT=%0d words=%0d max_held=%0d full_cycles=%0d max_rlevel=%0d",
               DEPTH, STAGES, whalf, rhalf, jit, rd_idx, max_held, n_full, max_rlevel);
    else
      $display("TB_RESULT FAIL tb_async_fifo errors=%0d", errors);
    $finish;
  end

  initial begin
    #(64'd2_000_000_000);
    $display("TB_RESULT FAIL tb_async_fifo timeout wr=%0d rd=%0d", wr_idx, rd_idx);
    $finish;
  end
endmodule
