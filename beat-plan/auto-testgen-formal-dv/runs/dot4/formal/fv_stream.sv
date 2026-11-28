module fv_stream (
  input clk,
  input rst_i,
  input in_valid,
  input [95:0] in_data,
  input out_ready_i,
  input f_pick
);
  wire in_ready, out_valid;
  wire [31:0] out_data;
  wire out_ready = out_ready_i;
  dot4 dut (.clk(clk), .rst(rst_i), .in_valid(in_valid), .out_valid(out_valid), .in_ready(in_ready), .out_ready(out_ready), .a(in_data[31:0]), .w(in_data[63:32]), .bias(in_data[95:64]), .y(out_data[31:0]));
  reg f_past_valid = 1'b0;
  always @(posedge clk) f_past_valid <= 1'b1;
  wire acc = in_valid && in_ready;
  wire emit = out_valid && out_ready;
  reg [3:0] f_inflight = 0;
  reg [3:0] f_wait = 0;
  reg f_armed = 1'b0, f_done = 1'b0;
  reg [3:0] f_ahead = 0;
  wire pick_now = !f_armed && acc && f_pick;
  wire passthru = pick_now && emit && (f_inflight == 0);
  wire tracked_out = f_armed && !f_done && emit && (f_ahead == 0);
  // The golden is applied to the input in the cycle it is accepted and the
  // EXPECTED OUTPUT is stored: DUT and golden then operate on the same input
  // variables, which keeps the data proof tractable for SAT/PDR.
  wire [31:0] exp_now;
  reg  [31:0] f_exp = 0;
  wire c_ok;
  ref_dot4 ref_now (
    .g_a(in_data[31:0]),
    .g_w(in_data[63:32]),
    .g_bias(in_data[95:64]),
    .g_y(exp_now[31:0]),
    .ok(),
    .constraints_ok(c_ok),
    .gcov_int32_wraps(),
    .gcov_products_cancel(),
    .bin_in_a_all_equal(),
    .bin_in_a_tie_at_max(),
    .bin_in_a_0__max(),
    .bin_in_a_0__min(),
    .bin_in_a_0__zero(),
    .bin_in_a_1__max(),
    .bin_in_a_1__min(),
    .bin_in_a_1__zero(),
    .bin_in_a_2__max(),
    .bin_in_a_2__min(),
    .bin_in_a_2__zero(),
    .bin_in_a_3__max(),
    .bin_in_a_3__min(),
    .bin_in_a_3__zero(),
    .bin_in_bias_max(),
    .bin_in_bias_min(),
    .bin_in_bias_zero(),
    .bin_in_w_all_equal(),
    .bin_in_w_tie_at_max(),
    .bin_in_w_0__max(),
    .bin_in_w_0__min(),
    .bin_in_w_0__zero(),
    .bin_in_w_1__max(),
    .bin_in_w_1__min(),
    .bin_in_w_1__zero(),
    .bin_in_w_2__max(),
    .bin_in_w_2__min(),
    .bin_in_w_2__zero(),
    .bin_in_w_3__max(),
    .bin_in_w_3__min(),
    .bin_in_w_3__zero(),
    .bin_out_y_max(),
    .bin_out_y_min(),
    .bin_out_y_zero(),
    .bnd_boundary_L8_cmp_gt1_eq(),
    .bnd_boundary_L8_cmp_gt1_m1(),
    .bnd_boundary_L8_cmp_gt1_p1(),
    .bnd_boundary_L8_cmp_lt2_eq(),
    .bnd_boundary_L8_cmp_lt2_m1(),
    .bnd_boundary_L8_cmp_lt2_p1(),
    .bnd_boundary_L9_cmp_eq1_eq(),
    .bnd_boundary_L9_cmp_eq1_m1(),
    .bnd_boundary_L9_cmp_eq1_p1()
  );
  always @(posedge clk) begin
    if (rst_i) begin
      f_inflight <= 0; f_wait <= 0; f_armed <= 1'b0; f_done <= 1'b0;
    end else begin
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
    a_capacity: assert (f_inflight <= 2);
    a_bounded_latency: assert (f_wait <= 3);
    a_data_matches_golden: assert (!(tracked_out && out_data != f_exp) &&
                                   !(passthru && out_data != exp_now));
    c_output: cover (emit);
    c_tracked_checked: cover (tracked_out);
    c_backpressure: cover (out_valid && !out_ready);
    c_input_stall: cover (in_valid && !in_ready);
    c_full: cover (f_inflight == 2);
  end
endmodule
