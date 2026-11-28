// dot_reduce.sv -- STAND-IN datapath for the pipelining and retiming experiments.
// Forge Feature 5 pack RTL. NOT the Forge engine MAC row: that RTL is not in this
// checkout, and no result from this block may be quoted as an engine result.
//
// LANES signed AW x AW products feed a binary adder tree. Inputs and the output are
// always registered. Two knobs move registers:
//   PIPE_TREE = 1  a register after the multipliers and after every adder level
//                  (structural pipelining, no retiming needed);
//   PIPE_OUT  = k  k extra register stages after the final sum, for a retiming tool
//                  to push back into the tree (yosys synth_xilinx -retime / abc -dff).
// Latency (in_valid -> out_valid) = 2 + PIPE_OUT + (PIPE_TREE ? LOG2(LANES) + 1 : 0).
module dot_reduce #(
  parameter int unsigned LANES     = 16,   // power of two, >= 2
  parameter int unsigned AW        = 8,    // operand width, signed
  parameter bit          PIPE_TREE = 1'b0,
  parameter int unsigned PIPE_OUT  = 0
) (
  input  logic                   clk,
  input  logic                   rst_n,
  input  logic                   in_valid,
  input  logic [LANES*AW-1:0]    a,        // LANES packed signed operands
  input  logic [LANES*AW-1:0]    w,
  output logic                   out_valid,
  output logic signed [2*AW+$clog2(LANES)-1:0] y
);

  localparam int unsigned LV   = $clog2(LANES);
  localparam int unsigned OUTW = 2*AW + LV;
  localparam int unsigned PW   = 2*AW;
  localparam int unsigned LAT = 2 + PIPE_OUT + (PIPE_TREE ? LV + 1 : 0);

  generate
    if (LANES < 2 || (1 << LV) != LANES) begin : g_bad_param
      dot_reduce__LANES_must_be_power_of_2 u_param_error ();
    end
  endgenerate

  // Input registers (no reset on data).
  logic [LANES*AW-1:0] a_q, w_q;
  always_ff @(posedge clk) begin
    a_q <= a;
    w_q <= w;
  end

  // Tree level l holds (LANES >> l) values of width PW + l.
  genvar l, i;
  generate
    for (l = 0; l <= LV; l++) begin : g_lvl
      localparam int unsigned N  = LANES >> l;
      localparam int unsigned WD = PW + l;
      logic [N*WD-1:0] val;
      logic [N*WD-1:0] q;
      if (l == 0) begin : g_mul
        for (i = 0; i < N; i++) begin : g_m
          assign val[i*WD +: WD] = $signed(a_q[i*AW +: AW]) * $signed(w_q[i*AW +: AW]);
        end
      end else begin : g_add
        for (i = 0; i < N; i++) begin : g_a
          assign val[i*WD +: WD] = $signed(g_lvl[l-1].q[(2*i)*(WD-1)   +: (WD-1)])
                                 + $signed(g_lvl[l-1].q[(2*i+1)*(WD-1) +: (WD-1)]);
        end
      end
      if (PIPE_TREE) begin : g_reg
        always_ff @(posedge clk) q <= val;
      end else begin : g_comb
        assign q = val;
      end
    end
  endgenerate

  // PIPE_OUT stages after the sum, then the output register.
  logic [OUTW-1:0] sum;
  assign sum = g_lvl[LV].q;

  logic [(PIPE_OUT+1)*OUTW-1:0] tail;
  assign tail[0 +: OUTW] = sum;
  generate
    for (i = 0; i < PIPE_OUT; i++) begin : g_out
      (* shreg_extract = "no" *) logic [OUTW-1:0] r_q;   // keep as flops (retimable), not an SRL
      always_ff @(posedge clk) r_q <= tail[i*OUTW +: OUTW];
      assign tail[(i+1)*OUTW +: OUTW] = r_q;
    end
  endgenerate

  always_ff @(posedge clk) y <= $signed(tail[PIPE_OUT*OUTW +: OUTW]);

  // Valid pipeline matches the data latency.
  logic [LAT-1:0] v_q;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) v_q <= '0;
    else        v_q <= {v_q[LAT-2:0], in_valid};
  end
  assign out_valid = v_q[LAT-1];

endmodule
