@echo off
setlocal

cd /d "%~dp0"

if not exist ".env.9router" (
  echo Chua co .env.9router
  echo Hay copy .env.9router.example thanh .env.9router va dien URL/KEY.
  goto :eof
)

echo === Danh sach model image ===
python nine_router_image.py discover

echo.
echo === Vi du thong tin model ===
echo python nine_router_image.py info --id openai/dall-e-3

echo.
echo === Vi du tao anh ===
echo python nine_router_image.py generate --model openai/dall-e-3 --prompt "watercolor mountains at sunrise" --size 1024x1024 --output out.png

endlocal
