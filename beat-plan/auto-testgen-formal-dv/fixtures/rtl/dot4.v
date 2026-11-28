// FIXTURE written in this session to exercise forge_testgen.
// It is NOT a Forge Build 6 block and makes no claim about Forge RTL.
//
// Valid/ready 2-stage pipeline:  y = wrap32( bias + sum_i a[i] * w[i] )
// a, w: 4 lanes of int8 (lane 0 in bits [7:0]); bias, y: int32.
module dot4 (
  input  wire               clk,
  input  wire               rst,
  input  wire               in_valid,
  output wire               in_ready,
  input  wire [31:0]        a,
  input  wire [31:0]        w,
  input  wire signed [31:0] bias,
  output wire               out_valid,
  input  wire               out_ready,
  output wire signed [31:0] y
);
  reg               v1, v2;
  reg signed [15:0] p0, p1, p2, p3;
  reg signed [31:0] b1, s2;

  wire adv2 = !v2 || out_ready;   // stage 2 register can take a new value
  wire adv1 = !v1 || adv2;        // stage 1 register can take a new value
  assign in_ready  = adv1;
  assign out_valid = v2;
  assign y         = s2;

  function signed [15:0] mul8(input [7:0] x, input [7:0] z);
    mul8 = $signed(x) * $signed(z);
  endfunction

  always @(posedge clk) begin
    if (rst) begin
      v1 <= 1'b0;
      v2 <= 1'b0;
    end else begin
      if (adv2) begin
        v2 <= v1;
        if (v1) s2 <= b1 + p0 + p1 + p2 + p3;
      end
      if (adv1) begin
        v1 <= in_valid;
        if (in_valid) begin
          p0 <= mul8(a[7:0],   w[7:0]);
          p1 <= mul8(a[15:8],  w[15:8]);
          p2 <= mul8(a[23:16], w[23:16]);
          p3 <= mul8(a[31:24], w[31:24]);
          b1 <= bias;
        end
      end
    end
  end
endmodule
