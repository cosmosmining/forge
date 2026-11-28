// tb_pipe_reg.sv -- pipe_reg output equals input delayed by exactly STAGES cycles.
`timescale 1ps/1ps
module tb_pipe_reg;
  parameter int WIDTH  = 12;
  parameter int STAGES = 3;
  localparam int HIST = 64;

  logic clk = 1'b0, rst_n = 1'b0, in_valid = 1'b0;
  logic [WIDTH-1:0] in_data = '0;
  logic out_valid;
  logic [WIDTH-1:0] out_data;
  logic             hv [0:HIST-1];
  logic [WIDTH-1:0] hd [0:HIST-1];
  integer t = 0, errors = 0, checked = 0, seed = 9, k;

  always #1000 clk = ~clk;
  pipe_reg #(.WIDTH(WIDTH), .STAGES(STAGES)) dut (
    .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_data(in_data), .out_valid(out_valid), .out_data(out_data));

  always @(negedge clk) begin
    in_valid <= $random(seed);
    in_data  <= WIDTH'($random(seed));
  end

  // After rising edge t settles, out must equal the input captured at edge
  // t - (STAGES-1) (STAGES = 0 or 1: the input captured at edge t itself).
  always @(posedge clk) if (rst_n) begin
    #1;
    hv[t % HIST] = in_valid;   // inputs change only at negedge, so this is what edge t captured
    hd[t % HIST] = in_data;
    if (t >= STAGES) begin
      k = (STAGES > 0) ? (t - (STAGES - 1)) % HIST : t % HIST;
      if (out_valid !== hv[k] || (hv[k] && out_data !== hd[k])) begin
        errors = errors + 1; $display("ERROR t=%0t mismatch at cycle %0d", $time, t);
      end
      checked = checked + 1;
    end
    t = t + 1;
  end

  initial begin
    repeat (2) @(posedge clk);
    @(negedge clk) rst_n = 1'b1;
    repeat (500) @(posedge clk);
    #10;
    if (errors == 0) $display("TB_RESULT PASS tb_pipe_reg STAGES=%0d checked=%0d", STAGES, checked);
    else             $display("TB_RESULT FAIL tb_pipe_reg errors=%0d", errors);
    $finish;
  end
endmodule
