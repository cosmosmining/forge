module fv_stream (
  input clk,
  input rst_i,
  input in_valid,
  input [15:0] in_data,
  input out_ready_i,
  input f_pick
);
  wire in_ready, out_valid;
  wire [15:0] out_data;
  wire out_ready = out_ready_i;
  sfifo dut (.clk(clk), .rst(rst_i), .in_valid(in_valid), .out_valid(out_valid), .in_ready(in_ready), .out_ready(out_ready), .in_data(in_data[15:0]), .out_data(out_data[15:0]));
  reg f_past_valid = 1'b0;
  always @(posedge clk) f_past_valid <= 1'b1;
  wire acc = in_valid && in_ready;
  wire emit = out_valid && out_ready;
  reg [3:0] f_inflight = 0;
  reg [3:0] f_wait = 0;
  reg [4:0] f_istall = 0;
  reg f_armed = 1'b0, f_done = 1'b0;
  reg [3:0] f_ahead = 0;
  wire pick_now = !f_armed && acc && f_pick;
  wire passthru = pick_now && emit && (f_inflight == 0);
  wire tracked_out = f_armed && !f_done && emit && (f_ahead == 0);
  // The golden is applied to the input in the cycle it is accepted and the
  // EXPECTED OUTPUT is stored: DUT and golden then operate on the same input
  // variables, which keeps the data proof tractable for SAT/PDR.
  wire [15:0] exp_now;
  reg  [15:0] f_exp = 0;
  wire c_ok;
  ref_sfifo ref_now (
    .g_in_data(in_data[15:0]),
    .g_out_data(exp_now[15:0]),
    .ok(),
    .constraints_ok(c_ok),
    .bin_in_in_data_max(),
    .bin_in_in_data_min(),
    .bin_out_out_data_max(),
    .bin_out_out_data_min()
  );
  always @(posedge clk) begin
    if (rst_i) begin
      f_inflight <= 0; f_wait <= 0; f_istall <= 0; f_armed <= 1'b0; f_done <= 1'b0;
    end else begin
      if (in_valid && !in_ready && out_ready) begin
        if (f_istall != {5{1'b1}}) f_istall <= f_istall + 1;
      end else f_istall <= 0;
      f_inflight <= f_inflight + (acc ? 1 : 0) - (emit ? 1 : 0);
      if (emit || f_inflight == 0 || (f_inflight == 1 && emit)) f_wait <= 0;
      else if (out_ready && f_wait != {4{1'b1}}) f_wait <= f_wait + 1;
      if (pick_now) begin
        f_armed <= 1'b1;
        f_exp <= exp_now;
        if (passthru) f_done <= 1'b1;
        else f_ahead <= f_inflight - (emit ? 1 : 0);
      end else if (f_armed && !f_done && emit) begin
        if (f_ahead == 0) f_done <= 1'b1;
        else f_ahead <= f_ahead - 1;
      end
    end
  end
  always @(*) if (!f_past_valid) assume (rst_i);
  always @(*) if (in_valid) assume (c_ok);
  always @(posedge clk) if (f_past_valid && !$past(rst_i) && !rst_i && $past(in_valid && !in_ready)) begin
    assume (in_valid);
    assume (in_data == $past(in_data));
  end
  always @(posedge clk) if (f_past_valid && $past(rst_i) && !rst_i && !in_valid) begin
    a_quiet_after_reset: assert (!out_valid);
  end
  always @(posedge clk) if (f_past_valid && !$past(rst_i) && !rst_i && $past(out_valid && !out_ready)) begin
    a_hold_valid: assert (out_valid);
    a_hold_data: assert (out_data == $past(out_data));
  end
  always @(*) if (!rst_i) begin
    a_no_spurious_output: assert (!emit || f_inflight != 0 || acc);
    a_capacity: assert (f_inflight <= 4);
    a_bounded_latency: assert (f_wait <= 3);
    a_input_progress: assert (f_istall <= 8);
    a_accepts_below_capacity: assert (!in_valid || in_ready || f_inflight >= 4);
    a_data_matches_golden: assert (!(tracked_out && out_data != f_exp) &&
                                   !(passthru && out_data != exp_now));
    c_output: cover (emit);
    c_tracked_checked: cover (tracked_out);
    c_backpressure: cover (out_valid && !out_ready);
    c_input_stall: cover (in_valid && !in_ready);
    c_full: cover (f_inflight == 4);
  end
endmodule
