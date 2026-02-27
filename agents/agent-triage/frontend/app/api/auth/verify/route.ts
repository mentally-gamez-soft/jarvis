import { NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest) {
  try {
    const { password } = await request.json();

    if (!password) {
      return NextResponse.json(
        { error: "Password is required" },
        { status: 400 }
      );
    }

    const adminKey = process.env.NEXT_ADMIN_KEY;

    if (!adminKey) {
      return NextResponse.json(
        { error: "Admin key not configured" },
        { status: 500 }
      );
    }

    if (password === adminKey) {
      return NextResponse.json({ success: true });
    }

    return NextResponse.json(
      { error: "Incorrect password" },
      { status: 401 }
    );
  } catch (error) {
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
