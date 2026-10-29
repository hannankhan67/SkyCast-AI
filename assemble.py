exec(open("fix_part1.py", encoding="utf-8").read())
part2 = open("fix_part2.py", encoding="utf-8").read()
part3 = open("fix_part3.py", encoding="utf-8").read()
new = part2 + part3
with open(path, "w", encoding="utf-8") as f:
    f.write(before + new + after)
print("OK")
