{ pkgs }: {
  deps = [
    pkgs.python311
    pkgs.python311Packages.fastapi
    pkgs.python311Packages.uvicorn
    pkgs.python311Packages.requests
    pkgs.python311Packages.jinja2
    pkgs.python311Packages.python-multipart
    pkgs.python311Packages.pydantic
    pkgs.python311Packages.typing-extensions
  ];
}
