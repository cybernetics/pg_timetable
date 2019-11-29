package main

import (
	"flag"
	"fmt"
	scheduler "github.com/cybertec-postgresql/pg_timetable/internal/scheduler"
)

/**
 * test_task is the utility to test shell tasks before using them in pg_timetable chains
 */

func main() {
	cmdPtr := flag.String("cmd", `bash`, "command to run")
	cmdArgs := flag.String("arg", `["-c", "uconv -x \"::Latin; ::Latin-ASCII;\" > orte_ansi.txt < orte.txt"]`, "arguments for the command")
	exitCode, err := scheduler.ExecuteShellCommand(*cmdPtr, []string{*cmdArgs})
	if err != nil {
		fmt.Println(err)
	}
	fmt.Printf("Exit code: %d\n", exitCode)
}
