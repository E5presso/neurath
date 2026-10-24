"""설치된 실행 파일을 실제로 호출할 때만 공식 Typer 앱을 시작한다."""

if __name__ == "__main__":
    from neurath.cli import cli

    cli()
