import argparse


def main(argv=None):
    parser = argparse.ArgumentParser(description="SONAR: monitor local de activaciones CPU")
    from . import __version__
    parser.add_argument("--version", action="version", version=f"SONAR {__version__}")
    parser.add_argument("--history-mib", type=int, default=None, help="Cuota reciente legada; el total sera mayor")
    parser.add_argument("--budget-mib", type=int, default=64, help="Presupuesto global de datos administrados")
    parser.add_argument("--work-mib", type=int, default=8)
    parser.add_argument("--recent-percent", type=int, default=70)
    parser.add_argument("--retention", choices=['combined', 'detail'], default='combined')
    parser.add_argument("--render-hz", type=float, default=30)
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("demo", help="Abrir fuente sintetica rotulada")
    replay = commands.add_parser("replay", help="Reproducir captura JSON + NPZ")
    replay.add_argument("path")
    args = parser.parse_args(argv)
    try:
        from .contracts import MonitorConfig
        from .app.main import run_standalone

        config = MonitorConfig(history_bytes=None if args.history_mib is None else args.history_mib*1024**2,
                               data_budget_bytes=args.budget_mib*1024**2, work_bytes=args.work_mib*1024**2,
                               recent_fraction=args.recent_percent/100, retention_mode=args.retention, render_hz=args.render_hz)
        return run_standalone(config, args.command, getattr(args, "path", None))
    except ImportError as exc:
        parser.exit(2, f"Falta dependencia de GUI. Instalar sonar-activaciones[gui]. {exc}\n")
    except (ValueError, OSError) as exc:
        parser.exit(2, f"SONAR: {exc}\n")

