# bash completion for monctl
_monctl_names() { monctl _complete "$1" 2>/dev/null; }

_monctl() {
    local cur prev cmd i nargs
    cur=${COMP_WORDS[COMP_CWORD]}
    prev=${COMP_WORDS[COMP_CWORD-1]}
    local commands="list status set brightness range schedule profile auto watch config tray"

    cmd= nargs=0
    for ((i = 1; i < COMP_CWORD; i++)); do
        case ${COMP_WORDS[i]} in
            -*) ;;
            *) if [[ -z $cmd ]]; then cmd=${COMP_WORDS[i]}; else ((nargs++)); fi ;;
        esac
    done

    if [[ -z $cmd ]]; then
        COMPREPLY=($(compgen -W "$commands -h --help --version" -- "$cur"))
        return
    fi
    local IFS=$'\n'
    case $cmd in
        status)
            if [[ $cur == -* ]]; then COMPREPLY=($(compgen -W "--all --json" -- "$cur"))
            else COMPREPLY=($(compgen -W "$(_monctl_names monitors)" -- "$cur")); fi ;;
        set)
            if ((nargs == 0)); then COMPREPLY=($(compgen -W "$(_monctl_names monitors)" -- "$cur"))
            else compopt -o nospace 2>/dev/null; COMPREPLY=($(compgen -S = -W "$(_monctl_names settings)" -- "$cur")); fi ;;
        brightness)
            ((nargs == 1)) && COMPREPLY=($(compgen -W "$(_monctl_names monitors)" -- "$cur")) ;;
        range)
            if ((nargs == 0)); then COMPREPLY=($(compgen -W "$(_monctl_names monitors | grep -vx all)" -- "$cur"))
            elif ((nargs == 1)); then COMPREPLY=($(compgen -W "reset" -- "$cur")); fi ;;
        schedule)
            if ((nargs == 0)); then COMPREPLY=($(compgen -W $'list\nadd\nremove' -- "$cur"))
            elif [[ ${COMP_WORDS[COMP_CWORD-nargs]} == remove ]]; then COMPREPLY=($(compgen -W "$(_monctl_names times)" -- "$cur"))
            elif ((nargs == 2)); then COMPREPLY=($(compgen -W "$(_monctl_names profiles)" -- "$cur")); fi ;;
        profile)
            if ((nargs == 0)); then COMPREPLY=($(compgen -W $'list\nshow\nsave\napply\ndelete' -- "$cur"))
            elif ((nargs == 1)); then COMPREPLY=($(compgen -W "$(_monctl_names profiles)" -- "$cur")); fi ;;
        auto)
            if [[ $cur == -* ]]; then COMPREPLY=($(compgen -W "--focused" -- "$cur"))
            elif ((nargs == 0)); then COMPREPLY=($(compgen -W $'list\non\noff\ndefault\nadd\nremove\nprocs\ngames' -- "$cur"))
            else
                local sub
                for ((i = 1; i < COMP_CWORD; i++)); do [[ ${COMP_WORDS[i]} == "$cmd" ]] && sub=${COMP_WORDS[i+1]} && break; done
                case $sub in
                    default) ((nargs == 1)) && COMPREPLY=($(compgen -W "$(_monctl_names profiles)" -- "$cur")) ;;
                    remove) ((nargs == 1)) && COMPREPLY=($(compgen -W "$(_monctl_names rules)" -- "$cur")) ;;
                    add)
                        if ((nargs == 1)); then COMPREPLY=($(compgen -W "$(_monctl_names games)" -- "$cur"))
                        elif ((nargs == 2)); then COMPREPLY=($(compgen -W "$(_monctl_names profiles)" -- "$cur")); fi ;;
                esac
            fi ;;
        watch) COMPREPLY=($(compgen -W "--interval" -- "$cur")) ;;
        config) ((nargs == 0)) && COMPREPLY=($(compgen -W "msigd" -- "$cur")) ;;
        tray) COMPREPLY=($(compgen -W "--window" -- "$cur")) ;;
    esac
}
complete -F _monctl monctl
