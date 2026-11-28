module fv_witness (
  input  [31:0] i_acc,
  input  [15:0] i_mult,
  input  [4:0] i_shift,
  input  [7:0] i_zp
);
  wire h_boundary_L13_cmp_lt1_m1;
  wire r_cok;
  ref_requant ref (
    .g_acc(i_acc),
    .g_mult(i_mult),
    .g_shift(i_shift),
    .g_zp(i_zp),
    .g_y(),
    .ok(),
    .constraints_ok(r_cok),
    .gcov_neg_round_tie(),
    .gcov_round_tie(),
    .gcov_sat_hi(),
    .gcov_sat_lo(),
    .bin_bin_max_shift_moves_y(),
    .bin_bin_zero_out_nonzero_acc(),
    .bin_in_acc_max(),
    .bin_in_acc_min(),
    .bin_in_acc_zero(),
    .bin_in_mult_max(),
    .bin_in_mult_min(),
    .bin_in_shift_max(),
    .bin_in_shift_min(),
    .bin_in_zp_max(),
    .bin_in_zp_min(),
    .bin_in_zp_zero(),
    .bin_out_y_max(),
    .bin_out_y_min(),
    .bin_out_y_zero(),
    .bnd_boundary_L12_cmp_gt1_eq(),
    .bnd_boundary_L12_cmp_gt1_m1(),
    .bnd_boundary_L12_cmp_gt1_p1(),
    .bnd_boundary_L13_cmp_lt1_eq(),
    .bnd_boundary_L13_cmp_lt1_m1(h_boundary_L13_cmp_lt1_m1),
    .bnd_boundary_L13_cmp_lt1_p1(),
    .bnd_boundary_L14_cmp_eq2_eq(),
    .bnd_boundary_L14_cmp_eq2_m1(),
    .bnd_boundary_L14_cmp_eq2_p1(),
    .bnd_boundary_L14_cmp_gt1_eq(),
    .bnd_boundary_L14_cmp_gt1_p1(),
    .bnd_boundary_L15_cmp_lt1_eq(),
    .bnd_boundary_L15_cmp_lt1_m1(),
    .bnd_boundary_L15_cmp_lt1_p1()
  );
  always @* begin
    assume (r_cok);
    c_boundary_L13_cmp_lt1_m1: cover (h_boundary_L13_cmp_lt1_m1);
  end
endmodule
