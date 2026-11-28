// -----------------------------------------------------------------------------
// DV-AGENT SELF-TEST FIXTURE. Written only to exercise the Forge DV agent in
// beat-plan/dv-verification-agent. It is NOT Forge RTL and NOT a Build 6 block.
// Nothing measured on this file says anything about Forge's own design.
// -----------------------------------------------------------------------------
// Piecewise-linear table, 8 segments chosen by x[15:13], registered output
// (latency 1, no handshake):  y = base[seg] + ((slope[seg] * x[12:0]) >>> 8)
module fx_pwl (
  input  logic               clk,
  input  logic signed [15:0] x,
  output logic signed [15:0] y
);
  logic        [2:0]  seg;
  logic        [12:0] frac;
  logic signed [15:0] base;
  logic signed [7:0]  slope;
  logic signed [22:0] slope_x;
  logic signed [22:0] frac_x;
  logic signed [22:0] prod;
  logic signed [22:0] sum;

  assign seg     = x[15:13];
  assign frac    = x[12:0];
  assign slope_x = {{15{slope[7]}}, slope};
  assign frac_x  = {10'd0, frac};

  always_comb begin
    case (seg)
      3'd0:    begin base = 16'sd0;      slope = 8'sd24;  end
      3'd1:    begin base = 16'sd768;    slope = 8'sd30;  end
      3'd2:    begin base = 16'sd1728;   slope = 8'sd31;  end
      3'd3:    begin base = 16'sd2720;   slope = 8'sd32;  end
      3'd4:    begin base = -16'sd18000; slope = -8'sd2;  end
      3'd5:    begin base = -16'sd18064; slope = 8'sd3;   end
      3'd6:    begin base = -16'sd17968; slope = 8'sd60;  end
      default: begin base = -16'sd16048; slope = 8'sd100; end
    endcase
    prod = slope_x * frac_x;
    sum  = $signed({{7{base[15]}}, base}) + (prod >>> 8);
  end

  always_ff @(posedge clk) y <= sum[15:0];
endmodule
