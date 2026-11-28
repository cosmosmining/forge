// FIXTURE written in this session to exercise forge_testgen.
// It is NOT a Forge Build 6 block and makes no claim about Forge RTL.
//
// Synchronous valid/ready FIFO, depth 4, 16-bit data.
module sfifo (
  input  wire        clk,
  input  wire        rst,
  input  wire        in_valid,
  output wire        in_ready,
  input  wire [15:0] in_data,
  output wire        out_valid,
  input  wire        out_ready,
  output wire [15:0] out_data
);
  reg [15:0] mem [0:3];
  reg [2:0]  wptr, rptr;                     // 2 address bits + wrap bit
  wire empty = (wptr == rptr);
  wire full  = (wptr[1:0] == rptr[1:0]) && (wptr[2] != rptr[2]);
  assign in_ready  = !full;
  assign out_valid = !empty;
  assign out_data  = mem[rptr[1:0]];
  always @(posedge clk) begin
    if (rst) begin
      wptr <= 3'd0;
      rptr <= 3'd0;
    end else begin
      if (in_valid && in_ready) begin
        mem[wptr[1:0]] <= in_data;
        wptr <= wptr + 3'd1;
      end
      if (out_valid && out_ready)
        rptr <= rptr + 3'd1;
    end
  end
endmodule
