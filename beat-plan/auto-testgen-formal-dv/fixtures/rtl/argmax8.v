// FIXTURE written in this session to exercise forge_testgen.
// It is NOT a Forge Build 6 block and makes no claim about Forge RTL.
//
// Index and value of the maximum of 8 signed int8 values; ties -> lowest index.
module argmax8 (
  input  wire [63:0]       x,      // 8 x int8, element 0 in bits [7:0]
  output reg  [2:0]        idx,
  output reg  signed [7:0] vmax
);
  integer i;
  always @* begin
    idx  = 3'd0;
    vmax = $signed(x[7:0]);
    for (i = 1; i < 8; i = i + 1) begin
      if ($signed(x[i*8 +: 8]) > vmax) begin
        vmax = $signed(x[i*8 +: 8]);
        idx  = i[2:0];
      end
    end
  end
endmodule
