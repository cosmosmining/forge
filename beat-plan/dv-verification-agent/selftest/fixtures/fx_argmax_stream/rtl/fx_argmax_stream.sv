// -----------------------------------------------------------------------------
// DV-AGENT SELF-TEST FIXTURE. Written only to exercise the Forge DV agent in
// beat-plan/dv-verification-agent. It is NOT Forge RTL and NOT a Build 6 block.
// Nothing measured on this file says anything about Forge's own design.
// -----------------------------------------------------------------------------
// Streaming argmax over int16 values with valid/ready and last.
// Per packet: idx = position of the maximum (earliest on ties), max_val = maximum.
module fx_argmax_stream #(
  parameter int IDX_W = 8
) (
  input  logic               clk,
  input  logic               rst_n,
  input  logic               in_valid,
  output logic               in_ready,
  input  logic signed [15:0] x,
  input  logic               in_last,
  output logic               out_valid,
  input  logic               out_ready,
  output logic [IDX_W-1:0]   idx,
  output logic signed [15:0] max_val
);
  logic [IDX_W-1:0]   cnt_q;
  logic [IDX_W-1:0]   best_idx_q;
  logic signed [15:0] best_q;
  logic               first_q;
  logic               better;
  logic               fire_in;
  logic               fire_out;

  assign better   = first_q || (x > best_q);
  assign in_ready = !out_valid || out_ready;
  assign fire_in  = in_valid && in_ready;
  assign fire_out = out_valid && out_ready;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      cnt_q      <= '0;
      best_idx_q <= '0;
      best_q     <= '0;
      first_q    <= 1'b1;
      out_valid  <= 1'b0;
      idx        <= '0;
      max_val    <= '0;
    end else begin
      if (fire_out) out_valid <= 1'b0;
      if (fire_in) begin
        if (in_last) begin
          idx       <= better ? cnt_q : best_idx_q;
          max_val   <= better ? x : best_q;
          out_valid <= 1'b1;
          cnt_q     <= '0;
          first_q   <= 1'b1;
        end else begin
          if (better) begin
            best_q     <= x;
            best_idx_q <= cnt_q;
          end
          cnt_q   <= cnt_q + 1'b1;
          first_q <= 1'b0;
        end
      end
    end
  end
endmodule
