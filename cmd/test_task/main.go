package main

import (
	"fmt"

	scheduler "github.com/cybertec-postgresql/pg_timetable/internal/scheduler"
	flags "github.com/jessevdk/go-flags"
)

/**
 * test_task is the utility to test shell tasks before using them in pg_timetable chains
 */

type cmdOptions struct {
	TaskName string   `short:"t" long:"taskname" description:"The name of the built-in task or an executable" required:"True"`
	Argument []string `short:"a" long:"argument" description:"Arguments to call in JSON notation"`
}

var opts cmdOptions

func main() {
	_, err := flags.Parse(&opts)
	fmt.Println(opts.Argument)
	exitCode, err := scheduler.ExecuteShellCommand(opts.TaskName, opts.Argument)
	if err != nil {
		fmt.Println(err)
	}
	fmt.Printf("Exit code: %d\n", exitCode)
}
