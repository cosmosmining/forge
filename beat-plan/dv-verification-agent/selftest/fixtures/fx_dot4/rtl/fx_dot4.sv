// -----------------------------------------------------------------------------
// DV-AGENT SELF-TEST FIXTURE. Written only to exercise the Forge DV agent in
// beat-plan/dv-verification-agent. It is NOT Forge RTL and NOT a Build 6 block.
// Nothing measured on this file says anything about Forge's own design.
// -----------------------------------------------------------------------------
// 4-lane int8 dot product plus int32 bias, two pipeline stages with valid:
//   y = wrap32(bias + sum_i a[i] * b[i]),  lane i in bits [8i+7:8i]
module fx_dot4 (
  input  logic               clk,
  input  logic               rst_n,
  input  logic               in_valid,
  input  logic        [31:0] a,
  input  logic        [31:0] b,
  input  logic signed [31:0] bias,
  output logic               out_valid,
  output logic signed [31:0] y
);
  logic signed [15:0] a0, a1, a2, a3;
  logic signed [15:0] b0, b1, b2, b3;
  logic signed [15:0] p0, p1, p2, p3;
  logic signed [31:0] bias_q;
  logic               v1_q;

  assign a0 = {{8{a[7]}},  a[7:0]};
  assign a1 = {{8{a[15]}}, a[15:8]};
  assign a2 = {{8{a[23]}}, a[23:16]};
  assign a3 = {{8{a[31]}}, a[31:24]};
  assign b0 = {{8{b[7]}},  b[7:0]};
  assign b1 = {{8{b[15]}}, b[15:8]};
  assign b2 = {{8{b[23]}}, b[23:16]};
  assign b3 = {{8{b[31]}}, b[31:24]};

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      v1_q      <= 1'b0;
      out_valid <= 1'b0;
    end else begin
      v1_q      <= in_valid;
      out_valid <= v1_q;
    end
  end

  always_ff @(posedge clk) begin
    if (in_valid) begin
      p0     <= a0 * b0;
      p1     <= a1 * b1;
      p2     <= a2 * b2;
      p3     <= a3 * b3;
      bias_q <= bias;
    end
    if (v1_q) begin
      y <= bias_q + {{16{p0[15]}}, p0} + {{16{p1[15]}}, p1}
                  + {{16{p2[15]}}, p2} + {{16{p3[15]}}, p3};
    end
  end
endmodule
