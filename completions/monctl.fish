# fish completion for monctl
set -l cmds list status set brightness range schedule profile auto watch config tray
function __monctl_names; monctl _complete $argv[1] 2>/dev/null; end
function __monctl_nargs  # words after the command, not counting the one being typed
    set -l t (commandline -opc)
    math (count $t) - 2
end

complete -c monctl -f
complete -c monctl -n "not __fish_seen_subcommand_from $cmds" -a list -d 'List monitors'
complete -c monctl -n "not __fish_seen_subcommand_from $cmds" -a status -d 'Show monitor settings'
complete -c monctl -n "not __fish_seen_subcommand_from $cmds" -a set -d 'Change settings (KEY=VALUE)'
complete -c monctl -n "not __fish_seen_subcommand_from $cmds" -a brightness -d 'Set brightness'
complete -c monctl -n "not __fish_seen_subcommand_from $cmds" -a range -d 'Brightness matching range'
complete -c monctl -n "not __fish_seen_subcommand_from $cmds" -a schedule -d 'Time-of-day profiles'
complete -c monctl -n "not __fish_seen_subcommand_from $cmds" -a profile -d 'Manage profiles'
complete -c monctl -n "not __fish_seen_subcommand_from $cmds" -a auto -d 'Automatic profiles'
complete -c monctl -n "not __fish_seen_subcommand_from $cmds" -a watch -d 'Run automatic profiles without the tray'
complete -c monctl -n "not __fish_seen_subcommand_from $cmds" -a config -d 'Show or change monctl settings'
complete -c monctl -n "not __fish_seen_subcommand_from $cmds" -a tray -d 'Run the tray icon'
complete -c monctl -n "not __fish_seen_subcommand_from $cmds" -l version -d 'Show version'

complete -c monctl -n "__fish_seen_subcommand_from status" -l all -d 'Every setting'
complete -c monctl -n "__fish_seen_subcommand_from status" -l json -d 'JSON output'
complete -c monctl -n "__fish_seen_subcommand_from status" -a "(__monctl_names monitors)"
complete -c monctl -n "__fish_seen_subcommand_from range; and test (__monctl_nargs) -eq 0" -a "(__monctl_names monitors | string match -v all)"
complete -c monctl -n "__fish_seen_subcommand_from set; and test (__monctl_nargs) -eq 0" -a "(__monctl_names monitors)"
complete -c monctl -n "__fish_seen_subcommand_from set; and test (__monctl_nargs) -ge 1" -a "(__monctl_names settings | string replace -r '\$' '=')"
complete -c monctl -n "__fish_seen_subcommand_from brightness; and test (__monctl_nargs) -eq 1" -a "(__monctl_names monitors)"
complete -c monctl -n "__fish_seen_subcommand_from schedule; and test (__monctl_nargs) -eq 0" -a "list add remove"
complete -c monctl -n "__fish_seen_subcommand_from schedule; and __fish_seen_subcommand_from remove" -a "(__monctl_names times)"
complete -c monctl -n "__fish_seen_subcommand_from schedule; and __fish_seen_subcommand_from add; and test (__monctl_nargs) -eq 2" -a "(__monctl_names profiles)"
complete -c monctl -n "__fish_seen_subcommand_from profile; and test (__monctl_nargs) -eq 0" -a "list show save apply delete"
complete -c monctl -n "__fish_seen_subcommand_from profile; and test (__monctl_nargs) -eq 1" -a "(__monctl_names profiles)"
complete -c monctl -n "__fish_seen_subcommand_from auto; and test (__monctl_nargs) -eq 0" -a "list on off default add remove procs games"
complete -c monctl -n "__fish_seen_subcommand_from auto; and __fish_seen_subcommand_from default" -a "(__monctl_names profiles)"
complete -c monctl -n "__fish_seen_subcommand_from auto; and __fish_seen_subcommand_from remove" -a "(__monctl_names rules)"
complete -c monctl -n "__fish_seen_subcommand_from auto; and __fish_seen_subcommand_from add; and test (__monctl_nargs) -eq 1" -a "(__monctl_names games)"
complete -c monctl -n "__fish_seen_subcommand_from auto; and __fish_seen_subcommand_from add; and test (__monctl_nargs) -eq 2" -a "(__monctl_names profiles)"
complete -c monctl -n "__fish_seen_subcommand_from auto" -l focused -d 'Only while its window is focused'
complete -c monctl -n "__fish_seen_subcommand_from watch" -l interval -x -d 'Seconds between checks'
complete -c monctl -n "__fish_seen_subcommand_from config" -a msigd
complete -c monctl -n "__fish_seen_subcommand_from tray" -l window -d 'Also open the window'
