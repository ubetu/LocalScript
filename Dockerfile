FROM python:3.14-slim

# System deps: Lua 5.4, luarocks, build tools for cjson compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
        lua5.4 liblua5.4-dev luarocks \
        gcc make curl \
    && luarocks install luacheck \
    && luarocks --lua-version=5.4 install lua-cjson \
    && ln -sf /usr/bin/lua5.4 /usr/local/bin/lua \
    && apt-get purge -y gcc make liblua5.4-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install Python dependencies (cached layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application source and resources
COPY src/ src/
COPY resources/ resources/
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
