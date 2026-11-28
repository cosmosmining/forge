// tb_dot_reduce.sv -- dot_reduce against a behavioural model, at its declared latency.
// Used for every pipelining variant so the timing experiments never trade correctness.
`timescale 1ps/1ps
module tb_dot_reduce;
  parameter int LANES     = 16;
  parameter int AW        = 8;
  parameter bit PIPE_TREE = 1'b0;
  parameter int PIPE_OUT  = 0;
  localparam int OUTW = 2*AW + $clog2(LANES);
  localparam int QSZ  = 64;

  logic clk = 1'b0, rst_n = 1'b0, in_valid = 1'b0;
  logic [LANES*AW-1:0] a = '0, w = '0;
  logic out_valid;
  logic signed [OUTW-1:0] y;

  always #1000 clk = ~clk;

  dot_reduce #(.LANES(LANES), .AW(AW), .PIPE_TREE(PIPE_TREE), .PIPE_OUT(PIPE_OUT)) dut (
    .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .a(a), .w(w), .out_valid(out_valid), .y(y));

  logic signed [OUTW-1:0] expq [0:QSZ-1];
  integer head = 0, tail = 0, checked = 0, errors = 0, seed = 3, i, n;

  function automatic logic signed [OUTW-1:0] model(input logic [LANES*AW-1:0] av, input logic [LANES*AW-1:0] wv);
    logic signed [OUTW-1:0] acc;
    logic signed [AW-1:0] ai, wi;
    integer k;
    acc = '0;
    for (k = 0; k < LANES; k = k + 1) begin
      ai = av[k*AW +: AW];
      wi = wv[k*AW +: AW];
      acc = acc + OUTW'(ai * wi);
    end
    return acc;
  endfunction

  always @(negedge clk) begin
    in_valid <= rst_n && ($random(seed) % 4 != 0);
    for (i = 0; i < LANES; i = i + 1) begin
      // include the extreme codes so the widest products and sums are exercised
      n = $random(seed) % 8;
      a[i*AW +: AW] <= (n == 0) ? {1'b1, {(AW-1){1'b0}}} : (n == 1) ? {1'b0, {(AW-1){1'b1}}} : AW'($random(seed));
      n = $random(seed) % 8;
      w[i*AW +: AW] <= (n == 0) ? {1'b1, {(AW-1){1'b0}}} : (n == 1) ? {1'b0, {(AW-1){1'b1}}} : AW'($random(seed));
    end
  end

  always @(posedge clk) if (rst_n) begin
    if (in_valid) begin expq[tail % QSZ] = model(a, w); tail = tail + 1; end
    if (out_valid) begin
      if (head >= tail) begin errors = errors + 1; $display("ERROR t=%0t out_valid with nothing expected", $time); end
      else begin
        if (y !== expq[head % QSZ]) begin
          errors = errors + 1; $display("ERROR t=%0t result %0d: got %0d expected %0d", $time, head, y, expq[head % QSZ]);
        end
        head = head + 1; checked = checked + 1;
      end
    end
  end

  initial begin
    repeat (3) @(posedge clk);
    @(negedge clk) rst_n = 1'b1;
    repeat (3000) @(posedge clk);
    if (checked < 2000) begin errors = errors + 1; $display("ERROR only %0d results checked", checked); end
    if (errors == 0) $display("TB_RESULT PASS tb_dot_reduce LANES=%0d AW=%0d PIPE_TREE=%0d PIPE_OUT=%0d checked=%0d", LANES, AW, PIPE_TREE, PIPE_OUT, checked);
    else             $display("TB_RESULT FAIL tb_dot_reduce errors=%0d", errors);
    $finish;
  end
endmodule
