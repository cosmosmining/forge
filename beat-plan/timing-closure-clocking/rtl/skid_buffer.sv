// skid_buffer.sv -- fully registered valid/ready pipeline stage (register slice).
// Forge Feature 5 pack RTL (not Forge engine RTL).
//
// Breaks both timing paths of a handshake channel: m_valid/m_data come from flops, and
// s_ready comes from a flop (it does not depend on m_ready combinationally). Full
// throughput: one word per cycle while m_ready stays high. The second register (the
// skid) catches the word that was already in flight when m_ready fell.
// Use between pipeline stages that sit far apart, and wherever a ready signal would
// otherwise run combinationally through several blocks.
module skid_buffer #(
  parameter int unsigned WIDTH = 32
) (
  input  logic             clk,
  input  logic             rst_n,
  input  logic             s_valid,
  output logic             s_ready,
  input  logic [WIDTH-1:0] s_data,
  output logic             m_valid,
  input  logic             m_ready,
  output logic [WIDTH-1:0] m_data
);

  logic             out_valid_q, skid_valid_q;
  logic [WIDTH-1:0] out_data_q,  skid_data_q;

`ifdef CDC_MUTANT_SKID_NO_BACKPRESSURE
  // Test-only mutation (formal/ negative test): always ready, so words get dropped.
  assign s_ready = 1'b1;
`else
  assign s_ready = !skid_valid_q;
`endif
  assign m_valid = out_valid_q;
  assign m_data  = out_data_q;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      out_valid_q  <= 1'b0;
      skid_valid_q <= 1'b0;
    end else if (m_ready || !out_valid_q) begin
      // Output register is free this cycle: refill it from the skid, else from input.
      if (skid_valid_q) begin
        out_valid_q  <= 1'b1;
        skid_valid_q <= 1'b0;
      end else begin
        out_valid_q  <= s_valid;
      end
    end else if (s_valid && s_ready) begin
      // Output stalled and a word arrives: park it in the skid register.
      skid_valid_q <= 1'b1;
    end
  end

  always_ff @(posedge clk) begin
    if (m_ready || !out_valid_q) begin
      out_data_q <= skid_valid_q ? skid_data_q : s_data;
    end
    if (!(m_ready || !out_valid_q) && s_valid && s_ready) begin
      skid_data_q <= s_data;
    end
  end

`ifdef FORMAL
  // Single clock: plain smtbmc/abc proof.
  reg f_past = 1'b0;
  always @(posedge clk) f_past <= 1'b1;
  initial assume(!rst_n);

  // Word accounting with an arbitrary tracked word (see cdc_handshake.sv).
  reg [3:0] f_in = 4'd0, f_out = 4'd0;
  (* anyconst *) logic [3:0]       f_idx;
  (* anyconst *) logic [WIDTH-1:0] f_val;
  always @(posedge clk) begin
    if (!rst_n) begin
      f_in <= 4'd0; f_out <= 4'd0;
    end else begin
      if (s_valid && s_ready) f_in  <= f_in  + 4'd1;
      if (m_valid && m_ready) f_out <= f_out + 4'd1;
    end
  end
  always @(*) if (rst_n && s_valid && s_ready && f_in == f_idx) assume(s_data == f_val);
  always @(*) if (rst_n && m_valid && f_out == f_idx) assert(m_data == f_val);

  wire [3:0] f_occ = f_in - f_out;
  always @(*) if (rst_n) begin
    assert(f_occ <= 4'd2);
    assert(f_occ == {2'b00, out_valid_q} + {2'b00, skid_valid_q});
    if (skid_valid_q) assert(out_valid_q);
  end

  // Handshake rules on the output side: a word offered and not taken stays put.
  always @(posedge clk) if (f_past && rst_n && $past(rst_n) && $past(m_valid && !m_ready)) begin
    assert(m_valid);
    assert(m_data == $past(m_data));
  end

  // Full throughput: if the consumer is always ready, the producer is never stalled.
  always @(posedge clk) if (f_past && rst_n && $past(rst_n) && $past(m_ready)) assert(s_ready);

  always @(*) cover(rst_n && skid_valid_q);
`endif

endmodule
