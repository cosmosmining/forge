// -----------------------------------------------------------------------------
// DV-AGENT SELF-TEST FIXTURE. Written only to exercise the Forge DV agent in
// beat-plan/dv-verification-agent. It is NOT Forge RTL and NOT a Build 6 block.
// Nothing measured on this file says anything about Forge's own design.
// -----------------------------------------------------------------------------
// int32 accumulator -> int8 requantisation (combinational):
//   y = clamp(((acc * mult) + round) >>> shift + zp, -128, 127)
//   round = 2**(shift-1) for shift > 0, else 0 (round half up)
module fx_requant (
  input  logic signed [31:0] acc,
  input  logic        [15:0] mult,
  input  logic        [4:0]  shift,
  input  logic signed [7:0]  zp,
  output logic signed [7:0]  y
);
  logic signed [48:0] acc_x;
  logic signed [48:0] mult_x;
  logic signed [48:0] prod;
  logic signed [48:0] rnd;
  logic signed [48:0] shifted;
  logic signed [49:0] zp_x;
  logic signed [49:0] biased;

  assign acc_x  = {{17{acc[31]}}, acc};
  assign mult_x = {33'd0, mult};
  assign zp_x   = {{42{zp[7]}}, zp};

  always_comb begin
    prod    = acc_x * mult_x;
    rnd     = (shift == 5'd0) ? 49'sd0 : (49'sd1 <<< (shift - 5'd1));
    shifted = (prod + rnd) >>> shift;
    biased  = $signed({shifted[48], shifted}) + zp_x;
    if (biased > 50'sd127)
      y = 8'sd127;
    else if (biased < -50'sd128)
      y = -8'sd128;
    else
      y = biased[7:0];
  end
endmodule
