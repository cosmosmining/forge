// FIXTURE written in this session to exercise forge_testgen.
// It is NOT a Forge Build 6 block and makes no claim about Forge RTL.
//
// int32 accumulator -> int8 requantize:
//   y = sat8( round_half_up(acc * mult / 2^shift) + zp )
module requant (
  input  wire signed [31:0] acc,
  input  wire        [15:0] mult,
  input  wire        [4:0]  shift,
  input  wire signed [7:0]  zp,
  output wire signed [7:0]  y
);
  wire signed [48:0] prod   = acc * $signed({1'b0, mult});           // 32 x 17 signed
  wire signed [48:0] half   = (shift == 5'd0) ? 49'sd0 : (49'sd1 <<< (shift - 5'd1));
  wire signed [48:0] scaled = (prod + half) >>> shift;
  wire signed [49:0] biased = scaled + zp;
  assign y = (biased > 50'sd127)  ? 8'sh7f :
             (biased < -50'sd128) ? 8'sh80 :
             biased[7:0];
endmodule
