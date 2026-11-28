// slr_crossing.sv -- valid/ready channel whose crossing wires are all flop-to-flop.
// Forge Feature 5 pack RTL (not Forge engine RTL).
//
// For an AMD SLR boundary (or a long ASIC route). AMD's guidance for UltraScale+ SLR
// crossings (UG949): leave a flop, cross on the super long line, land in a flop, with
// no logic in between; those flops can then be the Laguna TX/RX registers
// (USER_SLL_REG in constraints/fpga_250mhz.tcl). A plain valid/ready channel cannot be
// cut that way, because ready runs backwards and combinationally. This module:
//   * sends data/valid forward through FWD_STAGES plain flops;
//   * returns a "room" credit backwards through BWD_STAGES plain flops (that is s_ready);
//   * lands words in a LUTRAM FIFO that keeps SKID = FWD_STAGES + BWD_STAGES entries
//     free for words that were already granted before "room" fell.
// formal/slr_crossing.sby proves no word is ever lost, duplicated, reordered or
// changed, that the FIFO never overflows, and that a consumer that is always ready
// gets one word per cycle. The SKID-1 mutant must fail, so the margin is exact.
//
// Latency: FWD_STAGES + 1 cycles from s_valid&&s_ready to m_valid.
module slr_crossing #(
  parameter int unsigned WIDTH      = 64,
  parameter int unsigned FWD_STAGES = 2,    // >= 1. 2 = TX flop in source SLR + RX flop in destination SLR
  parameter int unsigned BWD_STAGES = 2,    // >= 1
  parameter int unsigned FIFO_DEPTH = 8     // power of two, >= FWD_STAGES + BWD_STAGES + 2
) (
  input  logic             clk,
  input  logic             rst_n,
  // source side (source SLR)
  input  logic             s_valid,
  output logic             s_ready,
  input  logic [WIDTH-1:0] s_data,
  // destination side (destination SLR)
  output logic             m_valid,
  input  logic             m_ready,
  output logic [WIDTH-1:0] m_data
);

  localparam int unsigned AW = $clog2(FIFO_DEPTH);
`ifdef CDC_MUTANT_SLR_SKID_SHORT
  localparam int unsigned SKID = FWD_STAGES + BWD_STAGES - 1;   // test-only: one short
`else
  localparam int unsigned SKID = FWD_STAGES + BWD_STAGES;
`endif

  generate
    if (FWD_STAGES < 1 || BWD_STAGES < 1) begin : g_bad_stages
      slr_crossing__STAGES_must_be_at_least_1 u_param_error ();
    end
    if (FIFO_DEPTH < FWD_STAGES + BWD_STAGES + 2) begin : g_bad_depth
      slr_crossing__FIFO_DEPTH_too_small_for_round_trip u_param_error ();
    end
  endgenerate

  // ------------------------------ source side ---------------------------------
  logic send;
  assign send = s_valid && s_ready;

  // --------------------- forward pipe (data + valid), no logic ----------------
  logic [FWD_STAGES:0]         fv;
  logic [(FWD_STAGES+1)*WIDTH-1:0] fd;
  assign fv[0]         = send;
  assign fd[0 +: WIDTH] = s_data;

  genvar i;
  generate
    for (i = 0; i < FWD_STAGES; i++) begin : g_fwd
      (* shreg_extract = "no" *) logic             v_q;
      (* shreg_extract = "no" *) logic [WIDTH-1:0] d_q;
      always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) v_q <= 1'b0;
        else        v_q <= fv[i];
      end
      always_ff @(posedge clk) d_q <= fd[i*WIDTH +: WIDTH];
      assign fv[i+1]                 = v_q;
      assign fd[(i+1)*WIDTH +: WIDTH] = d_q;
    end
  endgenerate

  // --------------------------- destination side --------------------------------
  localparam int unsigned ROOM_MAX_I = FIFO_DEPTH - SKID;      // room while count < this
  localparam logic [AW:0]  ROOM_MAX   = ROOM_MAX_I[AW:0];

  logic            push;
  logic [WIDTH-1:0] push_data;
  logic            empty;
  /* verilator lint_off UNUSEDSIGNAL */
  logic            full;     // read only by the formal properties (never pushed while full)
  /* verilator lint_on UNUSEDSIGNAL */
  logic [AW:0]     count;
  logic            room;

  assign push      = fv[FWD_STAGES];
  assign push_data = fd[FWD_STAGES*WIDTH +: WIDTH];

  sync_fifo_lutram #(.WIDTH(WIDTH), .DEPTH(FIFO_DEPTH)) u_rx_fifo (
    .clk(clk), .rst_n(rst_n),
    .push(push), .wdata(push_data),
    .pop(m_valid && m_ready), .rdata(m_data),
    .empty(empty), .full(full), .count(count));

  assign m_valid = !empty;

  // Room for every word that may still arrive after this cycle's decision:
  // count + SKID < FIFO_DEPTH.
  assign room = (count < ROOM_MAX);

  // ------------------------ backward pipe (credit), no logic --------------------
  logic [BWD_STAGES:0] bv;
  assign bv[0] = room;
  generate
    for (i = 0; i < BWD_STAGES; i++) begin : g_bwd
      (* shreg_extract = "no" *) logic r_q;
      always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) r_q <= 1'b0;
        else        r_q <= bv[i];
      end
      assign bv[i+1] = r_q;
    end
  endgenerate

  assign s_ready = bv[BWD_STAGES];

`ifdef FORMAL
  reg f_past = 1'b0;
  always @(posedge clk) f_past <= 1'b1;
  initial assume(!rst_n);
  always @(posedge clk) if (f_past && $past(rst_n)) assume(rst_n);

  // No word is ever pushed into a full receive FIFO.
  always @(*) if (rst_n) assert(!(push && full));

  // Word accounting with an arbitrary tracked word.
  reg [4:0] f_in = 5'd0, f_out = 5'd0;
  (* anyconst *) logic [4:0]       f_idx;
  (* anyconst *) logic [WIDTH-1:0] f_val;
  always @(posedge clk) begin
    if (!rst_n) begin
      f_in <= 5'd0; f_out <= 5'd0;
    end else begin
      if (send)               f_in  <= f_in  + 5'd1;
      if (m_valid && m_ready) f_out <= f_out + 5'd1;
    end
  end
  always @(*) if (rst_n && send && f_in == f_idx) assume(s_data == f_val);
  always @(*) if (rst_n && m_valid && f_out == f_idx) assert(m_data == f_val);

  // Everything sent is either in the forward pipe or in the FIFO.
  wire [4:0] f_occ = f_in - f_out;
  wire [4:0] f_cnt = count;                 // zero-extended FIFO occupancy
  integer k;
  reg [4:0] f_pipe;
  always @(*) begin
    f_pipe = 5'd0;
    for (k = 1; k <= FWD_STAGES; k = k + 1) f_pipe = f_pipe + {4'd0, fv[k]};
  end
  always @(*) if (rst_n) assert(f_occ == f_pipe + f_cnt);

`ifdef SLR_THROUGHPUT
  // Throughput task: producer always has data, consumer always ready.
  reg [3:0] f_cyc = 4'd0;
  always @(posedge clk) if (rst_n && f_cyc != 4'hF) f_cyc <= f_cyc + 4'd1;
  always @(*) if (rst_n) begin assume(s_valid); assume(m_ready); end
  always @(*) if (rst_n && f_cyc > BWD_STAGES) assert(s_ready);
`endif

  always @(*) cover(rst_n && full);
`endif

endmodule
