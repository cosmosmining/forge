// fo4_chain.v -- gate-level FO4 chain for flows/asic/fo4.tcl (ASAP7 RVT INVx1).
// Stage s<k> drives s<k+1> plus three load inverters, i.e. a fanout of four.
module fo4_chain (input in, output out);
  wire [6:0] n;
  wire [17:0] dangling;
  INVx1_ASAP7_75t_R s0 (.A(in), .Y(n[0]));
  INVx1_ASAP7_75t_R l0_0 (.A(n[0]), .Y(dangling[0]));
  INVx1_ASAP7_75t_R l0_1 (.A(n[0]), .Y(dangling[1]));
  INVx1_ASAP7_75t_R l0_2 (.A(n[0]), .Y(dangling[2]));
  INVx1_ASAP7_75t_R s1 (.A(n[0]), .Y(n[1]));
  INVx1_ASAP7_75t_R l1_0 (.A(n[1]), .Y(dangling[3]));
  INVx1_ASAP7_75t_R l1_1 (.A(n[1]), .Y(dangling[4]));
  INVx1_ASAP7_75t_R l1_2 (.A(n[1]), .Y(dangling[5]));
  INVx1_ASAP7_75t_R s2 (.A(n[1]), .Y(n[2]));
  INVx1_ASAP7_75t_R l2_0 (.A(n[2]), .Y(dangling[6]));
  INVx1_ASAP7_75t_R l2_1 (.A(n[2]), .Y(dangling[7]));
  INVx1_ASAP7_75t_R l2_2 (.A(n[2]), .Y(dangling[8]));
  INVx1_ASAP7_75t_R s3 (.A(n[2]), .Y(n[3]));
  INVx1_ASAP7_75t_R l3_0 (.A(n[3]), .Y(dangling[9]));
  INVx1_ASAP7_75t_R l3_1 (.A(n[3]), .Y(dangling[10]));
  INVx1_ASAP7_75t_R l3_2 (.A(n[3]), .Y(dangling[11]));
  INVx1_ASAP7_75t_R s4 (.A(n[3]), .Y(n[4]));
  INVx1_ASAP7_75t_R l4_0 (.A(n[4]), .Y(dangling[12]));
  INVx1_ASAP7_75t_R l4_1 (.A(n[4]), .Y(dangling[13]));
  INVx1_ASAP7_75t_R l4_2 (.A(n[4]), .Y(dangling[14]));
  INVx1_ASAP7_75t_R s5 (.A(n[4]), .Y(n[5]));
  INVx1_ASAP7_75t_R l5_0 (.A(n[5]), .Y(dangling[15]));
  INVx1_ASAP7_75t_R l5_1 (.A(n[5]), .Y(dangling[16]));
  INVx1_ASAP7_75t_R l5_2 (.A(n[5]), .Y(dangling[17]));
  INVx1_ASAP7_75t_R s6 (.A(n[5]), .Y(n[6]));
  assign out = n[6];
endmodule
