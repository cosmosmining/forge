// pipe_reg.sv -- fixed-latency pipeline (valid + data), STAGES flops deep.
// Forge Feature 5 pack RTL (not Forge engine RTL).
//
// For paths with no backpressure: datapath balancing, long wires inside one SLR,
// fan-out trees. STAGES = 0 is a wire. Data flops have no reset (cheaper, retimable,
// Laguna-friendly); only the valid bits are reset. shreg_extract="no" keeps Vivado and
// yosys from packing the chain into an SRL, which would remove the timing benefit.
module pipe_reg #(
  parameter int unsigned WIDTH  = 32,
  parameter int unsigned STAGES = 1
) (
  input  logic             clk,
  input  logic             rst_n,
  input  logic             in_valid,
  input  logic [WIDTH-1:0] in_data,
  output logic             out_valid,
  output logic [WIDTH-1:0] out_data
);

  generate
    if (STAGES == 0) begin : g_wire
      // clk and rst_n are not needed for a wire; keep them visibly "used" for lint.
      /* verilator lint_off UNUSEDSIGNAL */
      logic unused_clk_rst;
      assign unused_clk_rst = clk ^ rst_n;
      /* verilator lint_on UNUSEDSIGNAL */
      assign out_valid = in_valid;
      assign out_data  = in_data;
    end else if (STAGES == 1) begin : g_one
      (* shreg_extract = "no" *) logic             v_q;
      (* shreg_extract = "no" *) logic [WIDTH-1:0] d_q;
      always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) v_q <= 1'b0;
        else        v_q <= in_valid;
      end
      always_ff @(posedge clk) d_q <= in_data;
      assign out_valid = v_q;
      assign out_data  = d_q;
    end else begin : g_multi
      (* shreg_extract = "no" *) logic [STAGES-1:0]       v_q;
      (* shreg_extract = "no" *) logic [STAGES*WIDTH-1:0] d_q;
      always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) v_q <= '0;
        else        v_q <= {v_q[STAGES-2:0], in_valid};
      end
      always_ff @(posedge clk) d_q <= {d_q[(STAGES-1)*WIDTH-1:0], in_data};
      assign out_valid = v_q[STAGES-1];
      assign out_data  = d_q[STAGES*WIDTH-1 -: WIDTH];
    end
  endgenerate

endmodule
