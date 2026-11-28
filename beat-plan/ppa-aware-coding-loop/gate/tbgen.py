"""Testbench generator for the locked correctness gate.

One testbench per block, generated from the GOLDEN top-level port list and the
block's stimulus spec in blocks.json. The same testbench is compiled once
against the golden RTL and once against the candidate RTL; each run writes a
cycle-by-cycle trace of every output. gate.py then compares the two traces.

Timing of one cycle (period 10 ns):
  t+0  posedge clk           (DUT registers update; RTL uses '<= #1')
  t+5  negedge clk           -> sample every output into the trace
  t+6  drive new inputs      (data, bits, synchronous resets)
  t+7  optional async-reset glitch: assert at t+7, release at t+8
       (a glitch never spans a clock edge, so a design that turned an
        asynchronous reset into a synchronous one gives a different trace)
"""


def _rand_bits(width):
    """Verilog expression: width random bits from $random(seed)."""
    chunks = (width + 31) // 32
    parts = ["$random(seed)"] * chunks
    if chunks == 1:
        return "$random(seed)"
    return "{" + ", ".join(parts) + "}"


def _data_field(lhs, width, corner_pct):
    """Code assigning lhs (width bits) a random or corner value."""
    w = width
    msb_only = "1'b1" if w == 1 else "{1'b1, {%d{1'b0}}}" % (w - 1)
    max_pos = "1'b0" if w == 1 else "{1'b0, {%d{1'b1}}}" % (w - 1)
    lines = [
        "      sel = $random(seed) & 32'h7fffffff;",
        "      if ((sel %% 100) < %d) begin" % corner_pct,
        "        case ((sel / 100) % 6)",
        "          0: %s = {%d{1'b0}};" % (lhs, w),
        "          1: %s = {%d{1'b1}};" % (lhs, w),
        "          2: %s = %d'd1;" % (lhs, w),
        "          3: %s = %s;" % (lhs, msb_only),
        "          4: %s = %s;" % (lhs, max_pos),
        "          default: %s = $random(seed) & 15;" % lhs,
        "        endcase",
        "      end else",
        "        %s = %s;" % (lhs, _rand_bits(w)),
    ]
    return "\n".join(lines)


RISCV_TASK = r"""
  // Random RV32I instruction (90 %) or random 32-bit word (10 %).
  task gen_instr;
    output [31:0] ins;
    reg [31:0] r;
    reg [4:0] rd, rs1, rs2;
    reg [2:0] f3;
    reg [11:0] imm;
    reg [19:0] imm20;
    begin
      r = $random(seed) & 32'h7fffffff;
      // bias register numbers towards x0..x7 so results get reused
      rd  = (($random(seed) & 1) ? ($random(seed) & 7) : ($random(seed) & 31));
      rs1 = (($random(seed) & 1) ? ($random(seed) & 7) : ($random(seed) & 31));
      rs2 = (($random(seed) & 1) ? ($random(seed) & 7) : ($random(seed) & 31));
      f3  = $random(seed) & 7;
      imm = $random(seed);
      imm20 = $random(seed);
      case (r % 20)
        0, 1, 2: ins = {(($random(seed) & 1) ? 7'b0100000 : 7'b0000000), rs2, rs1, f3, rd, 7'b0110011}; // OP
        3, 4, 5: begin                                                                                // OP-IMM
                   if (f3 == 3'b001 || f3 == 3'b101)
                     ins = {(($random(seed) & 1) ? 7'b0100000 : 7'b0000000), imm[4:0], rs1, f3, rd, 7'b0010011};
                   else
                     ins = {imm, rs1, f3, rd, 7'b0010011};
                 end
        6, 7:    ins = {imm, rs1, f3, rd, 7'b0000011};                    // LOAD
        8, 9:    ins = {imm[11:5], rs2, rs1, f3, imm[4:0], 7'b0100011};   // STORE
        10, 11, 12: ins = {imm[11:5], rs2, rs1, f3, imm[4:0], 7'b1100011}; // BRANCH
        13:      ins = {imm20, rd, 7'b1101111};                          // JAL
        14:      ins = {imm, rs1, 3'b000, rd, 7'b1100111};               // JALR
        15:      ins = {imm20, rd, 7'b0110111};                          // LUI
        16:      ins = {imm20, rd, 7'b0010111};                          // AUIPC
        17:      ins = {imm, rs1, f3, rd, 7'b1110011};                   // SYSTEM
        default: ins = $random(seed);                                    // anything
      endcase
    end
  endtask
"""


def generate_tb(top, ports, stim, module_name="tb"):
    """ports: list of (name, direction, width) in golden declaration order."""
    clock = stim["clock"]
    spec = stim.get("inputs", {})
    inputs = [(n, w) for (n, d, w) in ports if d == "input" and n != clock]
    outputs = [(n, w) for (n, d, w) in ports if d == "output"]
    if any(d == "inout" for (_, d, _) in ports):
        raise ValueError("inout ports are not supported by the gate")

    L = []
    L.append("`timescale 1ns/1ps")
    L.append("module %s;" % module_name)
    L.append("  reg %s;" % clock)
    for n, w in inputs:
        L.append("  reg [%d:0] %s;" % (w - 1, n))
    for n, w in outputs:
        L.append("  wire [%d:0] %s;" % (w - 1, n))
    conns = ["." + n + "(" + n + ")" for (n, d, w) in ports]
    L.append("  %s dut (%s);" % (top, ", ".join(conns)))
    L.append("  integer seed, cycles, cyc, fd, sel;")
    L.append("  reg [1023:0] tracefile;")
    # per-reset state
    resets = [(n, w) for (n, w) in inputs if spec.get(n, {}).get("kind") == "reset"]
    for n, _ in resets:
        L.append("  integer rcnt_%s;" % n)
    if any(spec.get(n, {}).get("kind") == "riscv_instr" for n, _ in inputs):
        L.append(RISCV_TASK)

    # drive task -----------------------------------------------------------
    L.append("  task drive_inputs;")
    L.append("    begin")
    for n, w in inputs:
        s = spec.get(n, {"kind": "data"})
        k = s.get("kind", "data")
        if k == "reset":
            act = s["active"]
            p = int(round(s.get("p", 0.0) * 100000))
            L.append("      if (rcnt_%s > 0) rcnt_%s = rcnt_%s - 1;" % (n, n, n))
            L.append("      else if ((($random(seed) & 32'h7fffffff) %% 100000) < %d) rcnt_%s = 1 + (($random(seed) & 32'h7fffffff) %% 3);" % (p, n))
            L.append("      %s = (rcnt_%s > 0) ? 1'b%d : 1'b%d;" % (n, n, act, 1 - act))
        elif k == "bit":
            p1 = int(round(s.get("p1", 0.5) * 1000))
            L.append("      %s = ((($random(seed) & 32'h7fffffff) %% 1000) < %d);" % (n, p1))
        elif k == "riscv_instr":
            L.append("      gen_instr(%s);" % n)
        elif k == "data":
            fields = s.get("fields", [w])
            if sum(fields) != w:
                raise ValueError("fields of %s do not add up to %d" % (n, w))
            corner = int(s.get("corner_pct", 35))
            lo = w
            for fw in fields:  # msb first
                hi = lo - 1
                lo = lo - fw
                L.append(_data_field("%s[%d:%d]" % (n, hi, lo), fw, corner))
        else:
            raise ValueError("unknown stimulus kind %s" % k)
    L.append("    end")
    L.append("  endtask")

    # main loop ------------------------------------------------------------
    L.append("  initial begin")
    L.append("    if (!$value$plusargs(\"seed=%d\", seed)) seed = 1;")
    L.append("    if (!$value$plusargs(\"cycles=%d\", cycles)) cycles = 1000;")
    L.append("    if (!$value$plusargs(\"trace=%s\", tracefile)) tracefile = \"trace.txt\";")
    L.append("    fd = $fopen(tracefile, \"w\");")
    L.append("    %s = 1'b0;" % clock)
    for n, _ in resets:
        L.append("    rcnt_%s = %d;" % (n, int(spec[n].get("init_cycles", 3))))
    L.append("    drive_inputs;")
    L.append("    for (cyc = 0; cyc < cycles; cyc = cyc + 1) begin")
    L.append("      #5 %s = 1'b1;" % clock)
    L.append("      #5 %s = 1'b0;" % clock)
    if outputs:
        fmt = " ".join(["%b"] * len(outputs))
        L.append("      $fdisplay(fd, \"%s\", %s);" % (fmt, ", ".join(n for n, _ in outputs)))
    L.append("      #1 drive_inputs;")
    for n, _ in resets:
        s = spec[n]
        if s.get("type") == "async" and s.get("p_glitch", 0) > 0:
            act = s["active"]
            pg = int(round(s["p_glitch"] * 100000))
            L.append("      if (rcnt_%s == 0 && ((($random(seed) & 32'h7fffffff) %% 100000) < %d)) begin" % (n, pg))
            L.append("        #1 %s = 1'b%d;" % (n, act))
            L.append("        #1 %s = 1'b%d;" % (n, 1 - act))
            L.append("      end")
    L.append("    end")
    L.append("    $fclose(fd);")
    L.append("    $finish;")
    L.append("  end")
    L.append("endmodule")
    return "\n".join(L) + "\n"
