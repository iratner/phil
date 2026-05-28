import { Scene } from "phaser";

export class Game extends Scene {
  camera: Phaser.Cameras.Scene2D.Camera;
  background: Phaser.GameObjects.Image;
  msg_text: Phaser.GameObjects.Text;

  constructor() {
    super("Game");
  }

  create() {
    this.camera = this.cameras.main;
    this.camera.setBackgroundColor(0xeeff00);

    this.background = this.add.image(512, 384, "background");
    this.background.setAlpha(0.5);

    this.msg_text = this.add.text(
      512,
      384,
      "Make something fun!\nand share it with us:\nsupport@phaser.io",
      {
        fontFamily: "Arial Black",
        fontSize: 38,
        color: "#ffffff",
        stroke: "#110000",
        strokeThickness: 8,
        align: "center",
      },
    );
    this.msg_text.setOrigin(0.5);
    const charging = this.add.image(400, 300, "charging");

    // Create a hit area that's the same size as the image
    charging.setInteractive();

    // Add visual feedback for the hit area
    charging.on("pointerdown", () => {
      console.log("Charging station clicked!");
      charging.setTint(0x00ff00); // Green when clicked
    });

    charging.on("pointerover", () => {
      charging.setScale(1.1); // Slightly bigger on hover
    });

    charging.on("pointerout", () => {
      charging.setScale(1.0); // Back to normal
      charging.clearTint(); // Remove tint
    });

    for (let i = 0; i < 5; i++) {
      const x = 15 + 93 * i;
      const y = 700;
      const block = this.add.image(x, y, "temp_block");
      block.setInteractive();
      this.input.setDraggable(block);
    }
  }
}
