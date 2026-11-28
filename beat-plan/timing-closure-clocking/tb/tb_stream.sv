// tb_stream.sv -- randomized single-clock test for the valid/ready blocks:
//   +DUT=skid  -> skid_buffer
//   +DUT=slr   -> slr_crossing (FWD_STAGES/BWD_STAGES/FIFO_DEPTH parameters)
// Phase 1 (random): random s_valid and m_ready; scoreboard checks order and data,
//   checks the "offered word holds" rule, and (slr) that the receive FIFO is never
//   pushed while full.
// Phase 2 (throughput): s_valid=1, m_ready=1 for 2000 cycles; pass only if the
//   channel moved at least 1990 words (one per cycle once the pipe is full).
`timescale 1ps/1ps
module tb_stream;
  parameter int WIDTH      = 32;
  parameter int USE_SLR    = 1;
  parameter int FWD_STAGES = 2;
  parameter int BWD_STAGES = 2;
  parameter int FIFO_DEPTH = 8;
  localparam int SBSZ = 1 << 16;

  logic clk = 1'b0, arst_n = 1'b0, rst_n;
  logic s_valid = 1'b0, m_ready = 1'b0;
  logic [WIDTH-1:0] s_data = '0;
  logic s_ready, m_valid;
  logic [WIDTH-1:0] m_data;

  always #1000 clk = ~clk;
  cdc_reset_sync u_rs (.clk(clk), .arst_n(arst_n), .rst_n(rst_n));

  generate
    if (USE_SLR) begin : g_slr
      slr_crossing #(.WIDTH(WIDTH), .FWD_STAGES(FWD_STAGES), .BWD_STAGES(BWD_STAGES), .FIFO_DEPTH(FIFO_DEPTH)) dut (
        .clk(clk), .rst_n(rst_n), .s_valid(s_valid), .s_ready(s_ready), .s_data(s_data),
        .m_valid(m_valid), .m_ready(m_ready), .m_data(m_data));
    end else begin : g_skid
      skid_buffer #(.WIDTH(WIDTH)) dut (
        .clk(clk), .rst_n(rst_n), .s_valid(s_valid), .s_ready(s_ready), .s_data(s_data),
        .m_valid(m_valid), .m_ready(m_ready), .m_data(m_data));
    end
  endgenerate

  logic [WIDTH-1:0] sb [0:SBSZ-1];
  integer sent = 0, rcvd = 0, errors = 0, seed = 1, cyc, phase = 1, tp_words = 0;
  integer valid_pct = 60, ready_pct = 55, n_words = 20000;
  logic held_valid = 1'b0;
  logic [WIDTH-1:0] held_data = '0;

  function automatic integer rnd(input integer m);
    integer r;
    r = $random(seed);
    if (r < 0) r = -r;
    return r % m;
  endfunction

  initial begin
    if (!$value$plusargs("SEED=%d", seed)) seed = 1;
    if (!$value$plusargs("VALID=%d", valid_pct)) valid_pct = 60;
    if (!$value$plusargs("READY=%d", ready_pct)) ready_pct = 55;
  end

  // Drive on negedge; keep an offered source word until it is accepted.
  always @(negedge clk) begin
    if (!rst_n) begin
      s_valid <= 1'b0; m_ready <= 1'b0;
    end else if (phase == 1) begin
      if (!s_valid || s_ready) begin
        s_valid <= (sent < n_words) && (rnd(100) < valid_pct);
        s_data  <= WIDTH'($random(seed));
      end
      m_ready <= (rnd(100) < ready_pct);
    end else begin
      s_valid <= 1'b1; s_data <= WIDTH'($random(seed)); m_ready <= 1'b1;
    end
  end

  always @(posedge clk) if (rst_n) begin
    if (s_valid && s_ready) begin sb[sent % SBSZ] = s_data; sent = sent + 1; end
    if (held_valid && (!m_valid || m_data !== held_data)) begin
      errors = errors + 1; $display("ERROR t=%0t offered word withdrawn or changed", $time);
    end
    if (m_valid && m_ready) begin
      if (rcvd >= sent) begin errors = errors + 1; $display("ERROR t=%0t delivered unsent word", $time); end
      else if (m_data !== sb[rcvd % SBSZ]) begin
        errors = errors + 1; $display("ERROR t=%0t word %0d got %h expected %h", $time, rcvd, m_data, sb[rcvd % SBSZ]);
      end
      rcvd = rcvd + 1;
      if (phase == 2) tp_words = tp_words + 1;
    end
    held_valid = m_valid && !m_ready;
    held_data  = m_data;
  end

  generate
    if (USE_SLR) begin : g_chk
      always @(posedge clk) if (rst_n && g_slr.dut.push && g_slr.dut.full) begin
        errors = errors + 1; $display("ERROR t=%0t receive FIFO pushed while full", $time);
      end
    end
  endgenerate

  initial begin : run
    repeat (5) @(posedge clk);
    @(negedge clk) arst_n = 1'b1;
    wait (sent >= n_words);
    // drain
    @(negedge clk); phase = 2;
    // throughput phase: count words in 2000 cycles after the pipe refills
    repeat (40) @(posedge clk);
    tp_words = 0;
    repeat (2000) @(posedge clk);
    if (tp_words < 1990) begin errors = errors + 1; $display("ERROR throughput %0d words in 2000 cycles", tp_words); end
    if (errors == 0)
      $display("TB_RESULT PASS tb_stream %s FWD=%0d BWD=%0d DEPTH=%0d random_words=%0d throughput=%0d/2000",
               USE_SLR ? "slr_crossing" : "skid_buffer", FWD_STAGES, BWD_STAGES, FIFO_DEPTH, n_words, tp_words);
    else
      $display("TB_RESULT FAIL tb_stream errors=%0d", errors);
    $finish;
  end

  initial begin
    #(64'd2_000_000_000);
    $display("TB_RESULT FAIL tb_stream timeout sent=%0d rcvd=%0d", sent, rcvd);
    $finish;
  end
endmodule
