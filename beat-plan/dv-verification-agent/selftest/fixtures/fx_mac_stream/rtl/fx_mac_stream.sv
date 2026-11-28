// -----------------------------------------------------------------------------
// DV-AGENT SELF-TEST FIXTURE. Written only to exercise the Forge DV agent in
// beat-plan/dv-verification-agent. It is NOT Forge RTL and NOT a Build 6 block.
// Nothing measured on this file says anything about Forge's own design.
// -----------------------------------------------------------------------------
// Streaming int8 x int8 multiply-accumulate with valid/ready and last:
//   for each packet (beats up to and including in_last) emit
//   acc_out = wrap32(sum a*b). One output slot; input stalls while it is full.
module fx_mac_stream (
  input  logic               clk,
  input  logic               rst_n,
  input  logic               in_valid,
  output logic               in_ready,
  input  logic signed [7:0]  a,
  input  logic signed [7:0]  b,
  input  logic               in_last,
  output logic               out_valid,
  input  logic               out_ready,
  output logic signed [31:0] acc_out
);
  logic signed [31:0] acc_q;
  logic signed [15:0] prod;
  logic signed [31:0] sum;
  logic               fire_in;
  logic               fire_out;

  assign prod     = {{8{a[7]}}, a} * {{8{b[7]}}, b};
  assign sum      = acc_q + {{16{prod[15]}}, prod};
  assign in_ready = !out_valid || out_ready;
  assign fire_in  = in_valid && in_ready;
  assign fire_out = out_valid && out_ready;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      acc_q     <= '0;
      acc_out   <= '0;
      out_valid <= 1'b0;
    end else begin
      if (fire_out) out_valid <= 1'b0;
      if (fire_in) begin
        if (in_last) begin
          acc_out   <= sum;
          out_valid <= 1'b1;
          acc_q     <= '0;
        end else begin
          acc_q <= sum;
        end
      end
    end
  end
endmodule
