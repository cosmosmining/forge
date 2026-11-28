module fv_witness (
  input  [31:0] i_a,
  input  [31:0] i_w,
  input  [31:0] i_bias
);
  wire h_boundary_L8_cmp_gt1_m1;
  wire h_boundary_L8_cmp_gt1_p1;
  wire r_cok;
  ref_dot4 ref (
    .g_a(i_a),
    .g_w(i_w),
    .g_bias(i_bias),
    .g_y(),
    .ok(),
    .constraints_ok(r_cok),
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
    .bnd_boundary_L8_cmp_gt1_m1(h_boundary_L8_cmp_gt1_m1),
    .bnd_boundary_L8_cmp_gt1_p1(h_boundary_L8_cmp_gt1_p1),
    .bnd_boundary_L8_cmp_lt2_eq(),
    .bnd_boundary_L8_cmp_lt2_m1(),
    .bnd_boundary_L8_cmp_lt2_p1(),
    .bnd_boundary_L9_cmp_eq1_eq(),
    .bnd_boundary_L9_cmp_eq1_m1(),
    .bnd_boundary_L9_cmp_eq1_p1()
  );
  always @* begin
    assume (r_cok);
    c_boundary_L8_cmp_gt1_m1: cover (h_boundary_L8_cmp_gt1_m1);
    c_boundary_L8_cmp_gt1_p1: cover (h_boundary_L8_cmp_gt1_p1);
  end
endmodule
