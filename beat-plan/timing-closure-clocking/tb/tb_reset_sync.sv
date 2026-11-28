// tb_reset_sync.sv -- cdc_reset_sync: asynchronous assert, synchronous release.
// Pass criteria: rst_n falls within 1 ps of arst_n (no clock edge needed), and
// rises exactly STAGES rising clock edges after arst_n is released, for releases at
// random points inside the clock period.
`timescale 1ps/1ps
module tb_reset_sync;
  parameter int STAGES = 3;
  logic clk = 1'b0, arst_n = 1'b0, rst_n;
  integer seed = 5, errors = 0, trial, edges, off;

  cdc_reset_sync #(.STAGES(STAGES)) dut (.clk(clk), .arst_n(arst_n), .rst_n(rst_n));

  always #1000 clk = ~clk;

  initial begin
    repeat (4) @(posedge clk);
    for (trial = 0; trial < 50; trial = trial + 1) begin
      // release at a random offset inside the period, never on a clock edge
      @(posedge clk);
      off = $random(seed); if (off < 0) off = -off; off = 1 + off % 998;
      #(off) arst_n = 1'b1;
      edges = 0;
      while (rst_n !== 1'b1) begin @(posedge clk); #1; edges = edges + 1; end
      if (edges != STAGES) begin errors = errors + 1; $display("ERROR trial %0d: released after %0d edges, expected %0d", trial, edges, STAGES); end
      // assert asynchronously, away from any edge; rst_n must follow within 1 ps
      @(posedge clk);
      off = $random(seed); if (off < 0) off = -off; off = 1 + off % 998;
      #(off) arst_n = 1'b0;
      #1;
      if (rst_n !== 1'b0) begin errors = errors + 1; $display("ERROR trial %0d: assertion not asynchronous", trial); end
    end
    if (errors == 0) $display("TB_RESULT PASS tb_reset_sync STAGES=%0d trials=50", STAGES);
    else             $display("TB_RESULT FAIL tb_reset_sync errors=%0d", errors);
    $finish;
  end
endmodule
