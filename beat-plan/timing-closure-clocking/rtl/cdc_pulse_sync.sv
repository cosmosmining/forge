// cdc_pulse_sync.sv -- moves single-cycle events from clk_src to clk_dst.
// Forge Feature 5 pack RTL (not Forge engine RTL).
//
// Toggle synchronizer with acknowledge. Each accepted source pulse becomes exactly one
// destination pulse, for any ratio of the two clocks. The acknowledge path makes
// src_busy high while an event is in flight; a pulse raised while busy is NOT
// accepted, so a source that can burst must check src_busy, or put a counter or a
// FIFO in front. formal/pulse_sync.sby proves that, with any clock interleaving, no
// accepted event is lost or duplicated.
module cdc_pulse_sync #(
  parameter int unsigned STAGES = 2
) (
  input  logic clk_src,
  input  logic rst_src_n,
  input  logic src_pulse,
  output logic src_busy,
  output logic src_accept,   // src_pulse && !src_busy: this pulse will be delivered

  input  logic clk_dst,
  input  logic rst_dst_n,
  output logic dst_pulse
);

  logic src_tgl;        // source toggle, flips once per accepted event
  logic dst_tgl_sync;   // src_tgl synchronized into clk_dst
  logic dst_tgl_q;      // last value seen in clk_dst (edge detect, and the acknowledge)
  logic ack_tgl_sync;   // dst_tgl_q synchronized back into clk_src

  assign src_accept = src_pulse && !src_busy;

  always_ff @(posedge clk_src or negedge rst_src_n) begin
    if (!rst_src_n)     src_tgl <= 1'b0;
    else if (src_accept) src_tgl <= ~src_tgl;
  end

  cdc_sync_bit #(.WIDTH(1), .STAGES(STAGES)) u_fwd_sync (
    .clk_dst(clk_dst), .rst_dst_n(rst_dst_n), .d_async(src_tgl), .q(dst_tgl_sync));

  always_ff @(posedge clk_dst or negedge rst_dst_n) begin
    if (!rst_dst_n) dst_tgl_q <= 1'b0;
    else            dst_tgl_q <= dst_tgl_sync;
  end

  assign dst_pulse = dst_tgl_sync ^ dst_tgl_q;

  cdc_sync_bit #(.WIDTH(1), .STAGES(STAGES)) u_ack_sync (
    .clk_dst(clk_src), .rst_dst_n(rst_src_n), .d_async(dst_tgl_q), .q(ack_tgl_sync));

`ifdef CDC_MUTANT_NO_BUSY
  // Test-only mutation (formal/ negative test): ignore the acknowledge path.
  assign src_busy = 1'b0;
`else
  assign src_busy = src_tgl ^ ack_tgl_sync;
`endif

`ifdef FORMAL
  // ---- environment: both resets held for the first two global steps, never again ----
  reg [1:0] f_gstep = 2'd0;
  always @($global_clock) if (f_gstep != 2'd3) f_gstep <= f_gstep + 2'd1;
  always @(*) if (f_gstep < 2'd2) begin assume(!rst_src_n); assume(!rst_dst_n); end
  always @($global_clock) if (f_gstep != 2'd0) begin
    if ($past(rst_src_n)) assume(rst_src_n);
    if ($past(rst_dst_n)) assume(rst_dst_n);
  end

  // ---- accounting: accepted events (src) vs delivered events (dst) ----
  reg [3:0] f_sent = 4'd0, f_rcvd = 4'd0;
  always @(posedge clk_src) if (rst_src_n && src_accept) f_sent <= f_sent + 4'd1;
  always @(posedge clk_dst) if (rst_dst_n && dst_pulse)  f_rcvd <= f_rcvd + 4'd1;
  wire [3:0] f_inflight = f_sent - f_rcvd;

  // Never more than one event in flight; never a delivery without an accepted event.
  always @(*) assert(f_inflight <= 4'd1);
  // src_busy is exactly "an event is still in flight or not yet acknowledged".
  always @(*) if (rst_src_n && rst_dst_n && f_inflight == 4'd1) assert(src_busy);

  // ---- reachability ----
  always @(*) cover(f_rcvd == 4'd3);
`endif

endmodule
